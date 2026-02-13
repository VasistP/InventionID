"""Centralized configuration for the Patent Agent API."""
import os

# S3
S3_BUCKET = os.environ.get("PATENT_S3_BUCKET", "patent-pdf-input-786827631714")
S3_INPUT_PREFIX = "input/"
S3_RESULTS_PREFIX = "results/"

# API
API_PORT = int(os.environ.get("API_PORT", "8000"))
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
MAX_UPLOAD_SIZE_MB = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "50"))
