from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import jwt

from app.config import get_settings


def create_access_token(user_id: str, email: str, is_admin: bool = False) -> str:
    s = get_settings()
    expire = datetime.now(UTC) + timedelta(minutes=s.jwt_access_token_expire_minutes)
    return jwt.encode(
        {
            "sub": user_id,
            "email": email,
            "type": "access",
            "is_admin": is_admin,
            "exp": expire,
        },
        s.jwt_secret_key,
        algorithm=s.jwt_algorithm,
    )


def create_refresh_token(user_id: str, email: str) -> str:
    s = get_settings()
    expire = datetime.now(UTC) + timedelta(days=s.jwt_refresh_token_expire_days)
    return jwt.encode(
        {"sub": user_id, "email": email, "type": "refresh", "exp": expire},
        s.jwt_secret_key,
        algorithm=s.jwt_algorithm,
    )


def decode_token(token: str) -> dict:
    """Raise JWTError on invalid or expired token."""
    s = get_settings()
    return jwt.decode(token, s.jwt_secret_key, algorithms=[s.jwt_algorithm])


def token_fingerprint(token: str) -> str:
    """SHA-256 hex digest — used as Redis blocklist key."""
    return hashlib.sha256(token.encode()).hexdigest()
