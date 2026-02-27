"""Patent Agent API — FastAPI application."""
import asyncio
import json
import threading
import time
import os
import boto3
from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from config import S3_BUCKET, S3_INPUT_PREFIX, S3_RESULTS_PREFIX, ALLOWED_ORIGINS, MAX_UPLOAD_SIZE_MB
from pipeline_runner import run_pipeline_with_progress, PipelineAlreadyRunningError, _pipeline_lock

app = FastAPI(title="Patent Analysis API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _s3():
    """Create a fresh S3 client so EC2 instance-role credentials are always current."""
    return boto3.Session().client("s3")

# Track current pipeline run so frontend can recover after disconnect
_current_run: dict = {}  # {"s3_key": ..., "result_key": ..., "status": ..., "progress": [...]}
_current_run_lock = threading.Lock()


# ── REST Endpoints ──────────────────────────────────────────


@app.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...)):
    """Upload a PDF to S3 and return the S3 key."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted")

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(400, f"File exceeds {MAX_UPLOAD_SIZE_MB}MB limit")

    # Prefix with timestamp to avoid collisions
    ts = int(time.time())
    safe_name = file.filename.replace(" ", "_")
    s3_key = f"{S3_INPUT_PREFIX}{ts}_{safe_name}"

    _s3().put_object(Bucket=S3_BUCKET, Key=s3_key, Body=contents, ContentType="application/pdf")

    return {"s3_key": s3_key, "filename": file.filename}


@app.get("/api/results/{s3_key:path}")
async def get_results(s3_key: str):
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
async def pipeline_status():
    """Check whether a pipeline is currently running and return progress."""
    with _current_run_lock:
        info = dict(_current_run) if _current_run else {}
    return {"busy": _pipeline_lock.locked(), **info}


# ── WebSocket Endpoint ──────────────────────────────────────


@app.websocket("/ws/pipeline/{s3_key:path}")
async def pipeline_websocket(websocket: WebSocket, s3_key: str):
    """
    Run the pipeline and stream progress over WebSocket.

    Client connects to /ws/pipeline/input/1707..._file.pdf
    Server sends JSON progress messages and a final completed/error message.
    """
    await websocket.accept()

    loop = asyncio.get_event_loop()
    progress_queue: asyncio.Queue = asyncio.Queue()

    def progress_callback(data: dict):
        """Thread-safe: push progress into the async queue and track globally."""
        with _current_run_lock:
            _current_run["progress"] = _current_run.get("progress", []) + [data]
            if data.get("result_key"):
                _current_run["result_key"] = data["result_key"]
            _current_run["last_stage"] = data
        asyncio.run_coroutine_threadsafe(progress_queue.put(data), loop)

    def run_in_thread():
        try:
            with _current_run_lock:
                _current_run.clear()
                _current_run["s3_key"] = s3_key
                _current_run["status"] = "running"
                _current_run["progress"] = []

            run_pipeline_with_progress(S3_BUCKET, s3_key, progress_callback=progress_callback)

            with _current_run_lock:
                _current_run["status"] = "completed"
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
            with _current_run_lock:
                _current_run["status"] = "error"
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


# ── Static Frontend ─────────────────────────────────────────
_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(_DIST, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        """Serve the React SPA for any non-API route."""
        return FileResponse(os.path.join(_DIST, "index.html"))
