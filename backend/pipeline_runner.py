"""Thread-safe wrapper that runs the pipeline with progress reporting."""
import threading
import time
import sys
import os

# Add src/ to Python path so we can import the pipeline
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

_pipeline_lock = threading.Lock()


class PipelineAlreadyRunningError(Exception):
    pass


def run_pipeline_with_progress(bucket, pdf_key, progress_callback=None):
    """
    Run the patent pipeline with progress reporting.

    Acquires a mutex so only one pipeline runs at a time.
    Raises PipelineAlreadyRunningError if another pipeline is in progress.
    """
    if not _pipeline_lock.acquire(blocking=False):
        raise PipelineAlreadyRunningError("A pipeline is already running")

    try:
        # ── Pipeline version switch ──────────────────────────────────────────
        # Vector-ranked: re-ranks all candidates by FAISS cosine similarity
        # before fetching details
        from full_pipeline_vector import run_pipeline
        # Arrival-order (fallback): selects patents by SerpAPI return order
        # from full_pipeline_cached import run_pipeline
        # ────────────────────────────────────────────────────────────────────

        start_time = time.time()

        def timed_callback(data: dict):
            if data.get("status") == "completed":
                data = {**data, "duration_seconds": round(time.time() - start_time, 1)}
            progress_callback(data)

        effective_callback = timed_callback if progress_callback else None
        result = run_pipeline(bucket, pdf_key, progress_callback=effective_callback)

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
        _pipeline_lock.release()
