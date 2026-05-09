"""GitHub OAuth + JWT authentication for the Patent Agent API."""
from datetime import datetime, timedelta, timezone

from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from config import (
    ALLOWED_EMAIL_DOMAIN,
    GITHUB_CLIENT_ID,
    GITHUB_CLIENT_SECRET,
    JWT_ALGORITHM,
    JWT_EXPIRE_HOURS,
    JWT_SECRET,
)

oauth = OAuth()
oauth.register(
    name="github",
    client_id=GITHUB_CLIENT_ID,
    client_secret=GITHUB_CLIENT_SECRET,
    access_token_url="https://github.com/login/oauth/access_token",
    authorize_url="https://github.com/login/oauth/authorize",
    api_base_url="https://api.github.com/",
    client_kwargs={"scope": "read:user user:email"},
)


async def get_github_primary_email(token: dict) -> str:
    """Fetch the user's primary verified email from the GitHub API."""
    resp = await oauth.github.get("user/emails", token=token)
    emails = resp.json()
    # Prefer primary + verified; fall back to any verified address
    for entry in emails:
        if entry.get("primary") and entry.get("verified"):
            return entry["email"]
    for entry in emails:
        if entry.get("verified"):
            return entry["email"]
    raise HTTPException(status_code=403, detail="No verified email on your GitHub account")


def create_access_token(user_id: str, email: str, name: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "name": name,
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def check_email_domain(email: str) -> None:
    if not email.lower().endswith(f"@{ALLOWED_EMAIL_DOMAIN}"):
        raise HTTPException(
            status_code=403,
            detail=f"Access restricted to @{ALLOWED_EMAIL_DOMAIN} accounts",
        )


_bearer = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    return verify_token(credentials.credentials)
