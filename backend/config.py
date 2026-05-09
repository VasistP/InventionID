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

# Auth — required keys raise KeyError on startup if missing
GITHUB_CLIENT_ID = os.environ["GITHUB_CLIENT_ID"]
GITHUB_CLIENT_SECRET = os.environ["GITHUB_CLIENT_SECRET"]
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "168"))  # 7 days
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")
ALLOWED_EMAIL_DOMAIN = os.environ.get("ALLOWED_EMAIL_DOMAIN", "gmail.com")
