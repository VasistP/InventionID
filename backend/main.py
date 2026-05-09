"""Patent Agent API — FastAPI application."""
import asyncio
import json
import threading
import time
import os
import boto3
from fastapi import FastAPI, Form, UploadFile, File, WebSocket, WebSocketDisconnect, HTTPException, Query, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel

from config import (
    S3_BUCKET, S3_INPUT_PREFIX, S3_RESULTS_PREFIX,
    ALLOWED_ORIGINS, MAX_UPLOAD_SIZE_MB,
    JWT_SECRET, FRONTEND_URL,
)
from pipeline_runner import (
    run_pipeline_with_progress, run_rerun_with_progress,
    PipelineAlreadyRunningError, _get_user_locks, _user_pipeline_locks,
)
from auth import oauth, create_access_token, verify_token, get_current_user, check_email_domain, get_github_primary_email

app = FastAPI(title="Patent Analysis API")

app.add_middleware(SessionMiddleware, secret_key=JWT_SECRET)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _s3():
    """Create a fresh S3 client so EC2 instance-role credentials are always current."""
    return boto3.Session().client("s3")


# Per-user run state and inputs — keyed by user_id (Google sub)
_user_runs: dict[str, dict] = {}
_user_inputs: dict[str, dict] = {}   # user_id -> {s3_key: invention_input}
_rerun_params: dict[str, dict] = {}  # user_id -> {rerun_id: params}


class RerunRequest(BaseModel):
    result_key: str
    required_keywords: list[str] = []
    optional_keywords: list[str] = []


# ── Auth Endpoints ───────────────────────────────────────────


@app.get("/auth/github")
async def auth_github(request: Request):
    """Redirect to GitHub OAuth consent screen."""
    redirect_uri = request.url_for("auth_callback")
    return await oauth.github.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request):
    """Handle GitHub OAuth callback, validate OSU email, issue JWT."""
    try:
        token = await oauth.github.authorize_access_token(request)
    except Exception:
        return RedirectResponse(url=f"{FRONTEND_URL}?error=oauth_failed")

    try:
        resp = await oauth.github.get("user", token=token)
        userinfo = resp.json()
        user_id = str(userinfo.get("id", ""))
        name = userinfo.get("name") or userinfo.get("login", "")

        # GitHub may not expose email in the profile — fetch it separately
        email = userinfo.get("email") or await get_github_primary_email(token)

        check_email_domain(email)
    except HTTPException:
        return RedirectResponse(url=f"{FRONTEND_URL}?error=unauthorized_domain")
    except Exception:
        return RedirectResponse(url=f"{FRONTEND_URL}?error=oauth_failed")

    jwt_str = create_access_token(user_id, email, name)
    return RedirectResponse(url=f"{FRONTEND_URL}?token={jwt_str}")


@app.get("/auth/me")
async def auth_me(user: dict = Depends(get_current_user)):
    """Return the current user's info — used by the frontend to validate a stored token."""
    return {"userId": user["sub"], "email": user["email"], "name": user.get("name", "")}


# ── REST Endpoints ──────────────────────────────────────────


@app.post("/api/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    user_invention_input: str = Form(""),
    current_user: dict = Depends(get_current_user),
):
    """Upload a PDF to S3 and return the S3 key."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted")

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(400, f"File exceeds {MAX_UPLOAD_SIZE_MB}MB limit")

    user_id = current_user["sub"]
    ts = int(time.time())
    safe_name = file.filename.replace(" ", "_")
    s3_key = f"{S3_INPUT_PREFIX}{user_id}/{ts}_{safe_name}"

    _s3().put_object(Bucket=S3_BUCKET, Key=s3_key, Body=contents, ContentType="application/pdf")
    _user_inputs.setdefault(user_id, {})[s3_key] = user_invention_input

    return {"s3_key": s3_key, "filename": file.filename}


@app.get("/api/results/{s3_key:path}")
async def get_results(s3_key: str, _user: dict = Depends(get_current_user)):
    """Fetch a completed report JSON from S3."""
    try:
        obj = _s3().get_object(Bucket=S3_BUCKET, Key=s3_key)
        body = json.loads(obj["Body"].read())
        return body
    except _s3().exceptions.NoSuchKey:
        raise HTTPException(404, "Report not found")
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch results: {e}")


@app.get("/api/status")
async def pipeline_status(current_user: dict = Depends(get_current_user)):
    """Check whether the current user's pipeline is running and return progress."""
    user_id = current_user["sub"]
    run_lock, pipeline_lock = _get_user_locks(user_id)
    with run_lock:
        info = dict(_user_runs.get(user_id, {}))
    return {"busy": pipeline_lock.locked(), **info}


# ── WebSocket Endpoints ──────────────────────────────────────


@app.websocket("/ws/pipeline/{s3_key:path}")
async def pipeline_websocket(websocket: WebSocket, s3_key: str, token: str = Query(...)):
    """
    Run the pipeline and stream progress over WebSocket.

    JWT is passed as ?token= query parameter (WebSocket headers not supported after upgrade).
    """
    await websocket.accept()

    try:
        current_user = verify_token(token)
    except HTTPException:
        await websocket.send_json({"stage": -1, "stage_name": "Auth error", "status": "error", "error": "Unauthorized"})
        await websocket.close(code=4001)
        return

    user_id = current_user["sub"]
    run_lock, _ = _get_user_locks(user_id)

    loop = asyncio.get_event_loop()
    progress_queue: asyncio.Queue = asyncio.Queue()

    def progress_callback(data: dict):
        """Thread-safe: push progress into the async queue and track per-user state."""
        with run_lock:
            run = _user_runs.setdefault(user_id, {})
            run["progress"] = run.get("progress", []) + [data]
            if data.get("result_key"):
                run["result_key"] = data["result_key"]
            run["last_stage"] = data
        asyncio.run_coroutine_threadsafe(progress_queue.put(data), loop)

    def run_in_thread():
        try:
            with run_lock:
                run = _user_runs.setdefault(user_id, {})
                run.clear()
                run["s3_key"] = s3_key
                run["status"] = "running"
                run["progress"] = []

            run_pipeline_with_progress(
                S3_BUCKET, s3_key,
                user_id=user_id,
                progress_callback=progress_callback,
                user_invention_input=_user_inputs.get(user_id, {}).get(s3_key, ""),
            )

            with run_lock:
                _user_runs.setdefault(user_id, {})["status"] = "completed"
        except PipelineAlreadyRunningError:
            asyncio.run_coroutine_threadsafe(
                progress_queue.put({
                    "stage": -1,
                    "stage_name": "Pipeline busy",
                    "status": "error",
                    "error": "A pipeline is already running. Please wait.",
                }),
                loop,
            )
        except Exception as e:
            with run_lock:
                _user_runs.setdefault(user_id, {})["status"] = "error"
            asyncio.run_coroutine_threadsafe(
                progress_queue.put({
                    "stage": -1,
                    "stage_name": "Pipeline error",
                    "status": "error",
                    "error": str(e),
                }),
                loop,
            )

    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()

    try:
        while True:
            msg = await progress_queue.get()
            await websocket.send_json(msg)
            if msg.get("status") == "error" or (msg.get("status") == "completed" and msg.get("stage") == 7):
                break
    except WebSocketDisconnect:
        pass  # Client disconnected; pipeline continues in background


# ── Rerun Endpoints ─────────────────────────────────────────


@app.post("/api/rerun")
async def setup_rerun(req: RerunRequest, current_user: dict = Depends(get_current_user)):
    """Register a keyword-refined rerun job and return a rerun_id."""
    try:
        _s3().head_object(Bucket=S3_BUCKET, Key=req.result_key)
    except Exception:
        raise HTTPException(404, "Original report not found in S3")

    user_id = current_user["sub"]
    rerun_id = f"rerun_{int(time.time())}_{abs(hash(req.result_key)) % 10000:04d}"
    _rerun_params.setdefault(user_id, {})[rerun_id] = {
        "result_key": req.result_key,
        "required_keywords": req.required_keywords,
        "optional_keywords": req.optional_keywords,
    }
    return {"rerun_id": rerun_id}


@app.websocket("/ws/rerun/{rerun_id}")
async def rerun_websocket(websocket: WebSocket, rerun_id: str, token: str = Query(...)):
    """Stream progress for a keyword-refined rerun over WebSocket."""
    await websocket.accept()

    try:
        current_user = verify_token(token)
    except HTTPException:
        await websocket.send_json({"stage": -1, "stage_name": "Auth error", "status": "error", "error": "Unauthorized"})
        await websocket.close(code=4001)
        return

    user_id = current_user["sub"]
    params = _rerun_params.get(user_id, {}).get(rerun_id)
    if not params:
        await websocket.send_json({
            "stage": -1, "stage_name": "Invalid rerun", "status": "error",
            "error": "Rerun ID not found or expired",
        })
        await websocket.close()
        return

    loop = asyncio.get_event_loop()
    progress_queue: asyncio.Queue = asyncio.Queue()

    def progress_callback(data: dict):
        asyncio.run_coroutine_threadsafe(progress_queue.put(data), loop)

    def run_in_thread():
        try:
            run_rerun_with_progress(
                S3_BUCKET,
                params["result_key"],
                params["required_keywords"],
                params["optional_keywords"],
                user_id=user_id,
                progress_callback=progress_callback,
            )
        except PipelineAlreadyRunningError:
            asyncio.run_coroutine_threadsafe(
                progress_queue.put({
                    "stage": -1, "stage_name": "Pipeline busy", "status": "error",
                    "error": "A full pipeline is running. Please wait and try again.",
                }),
                loop,
            )
        except Exception as e:
            asyncio.run_coroutine_threadsafe(
                progress_queue.put({
                    "stage": -1, "stage_name": "Rerun error", "status": "error",
                    "error": str(e),
                }),
                loop,
            )

    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()

    try:
        while True:
            msg = await progress_queue.get()
            await websocket.send_json(msg)
            if msg.get("status") == "error" or (msg.get("status") == "completed" and msg.get("stage") == 7):
                break
    except WebSocketDisconnect:
        pass  # Client disconnected; rerun continues in background


# ── Static Frontend ─────────────────────────────────────────
_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(_DIST, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        """Serve the React SPA for any non-API route."""
        return FileResponse(os.path.join(_DIST, "index.html"))
