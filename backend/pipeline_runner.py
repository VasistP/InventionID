"""Thread-safe wrapper that runs the pipeline with progress reporting."""
import threading
import time
import sys
import os

# Add src/ to Python path so we can import the pipeline
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

_bootstrap_lock = threading.Lock()
_user_run_locks: dict[str, threading.Lock] = {}
_user_pipeline_locks: dict[str, threading.Lock] = {}


class PipelineAlreadyRunningError(Exception):
    pass


def _get_user_locks(user_id: str) -> tuple[threading.Lock, threading.Lock]:
    """Return (run_lock, pipeline_lock) for the given user, creating them if needed."""
    if user_id not in _user_run_locks:
        with _bootstrap_lock:
            if user_id not in _user_run_locks:
                _user_run_locks[user_id] = threading.Lock()
                _user_pipeline_locks[user_id] = threading.Lock()
    return _user_run_locks[user_id], _user_pipeline_locks[user_id]


def run_rerun_with_progress(
    bucket,
    result_key,
    required_keywords,
    optional_keywords,
    user_id: str,
    progress_callback=None,
):
    """Run pipeline stages 2-7 (keyword-refined rerun) with progress reporting.

    Does not acquire the pipeline mutex — reruns only write to a new S3 key.
    Raises PipelineAlreadyRunningError if the user's full pipeline is currently running.
    """
    _, pipeline_lock = _get_user_locks(user_id)
    if pipeline_lock.locked():
        raise PipelineAlreadyRunningError("A full pipeline is already running")

    from full_pipeline_vector import run_pipeline_from_search

    start_time = time.time()

    def timed_callback(data: dict):
        if data.get("status") == "completed":
            data = {**data, "duration_seconds": round(time.time() - start_time, 1)}
        if progress_callback:
            progress_callback(data)

    effective_callback = timed_callback if progress_callback else None

    try:
        result = run_pipeline_from_search(
            bucket, result_key,
            required_keywords=required_keywords,
            optional_keywords=optional_keywords,
            progress_callback=effective_callback,
        )
        if "error" in result and progress_callback:
            progress_callback({
                "stage": -1,
                "stage_name": "Rerun failed",
                "status": "error",
                "error": result["error"],
            })
        return result
    except PipelineAlreadyRunningError:
        raise
    except Exception as e:
        if progress_callback:
            progress_callback({
                "stage": -1,
                "stage_name": "Rerun error",
                "status": "error",
                "error": str(e),
            })
        raise


def run_pipeline_with_progress(
    bucket,
    pdf_key,
    user_id: str,
    progress_callback=None,
    user_invention_input="",
):
    """
    Run the patent pipeline with progress reporting.

    Acquires a per-user mutex so only one full pipeline runs per user at a time.
    Raises PipelineAlreadyRunningError if this user already has a pipeline in progress.
    """
    _, pipeline_lock = _get_user_locks(user_id)
    if not pipeline_lock.acquire(blocking=False):
        raise PipelineAlreadyRunningError("A pipeline is already running")

    try:
        from full_pipeline_vector import run_pipeline

        start_time = time.time()

        def timed_callback(data: dict):
            if data.get("status") == "completed":
                data = {**data, "duration_seconds": round(time.time() - start_time, 1)}
            progress_callback(data)

        effective_callback = timed_callback if progress_callback else None
        result = run_pipeline(
            bucket, pdf_key,
            progress_callback=effective_callback,
            user_invention_input=user_invention_input,
        )

        if "error" in result:
            if progress_callback:
                progress_callback({
                    "stage": -1,
                    "stage_name": "Pipeline failed",
                    "status": "error",
                    "error": result["error"],
                })

        return result
    except PipelineAlreadyRunningError:
        raise
    except Exception as e:
        if progress_callback:
            progress_callback({
                "stage": -1,
                "stage_name": "Pipeline error",
                "status": "error",
                "error": str(e),
            })
        raise
    finally:
        pipeline_lock.release()
