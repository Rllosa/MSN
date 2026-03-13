from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Cookie, HTTPException, Response, status
import jwt
from sqlalchemy import text

from app.api.schemas import LoginRequest, TokenResponse, UserInfo
from app.auth.dependencies import CurrentUser
from app.auth.hashing import verify_password
from app.auth.tokens import (
    create_access_token,
    create_refresh_token,
    decode_token,
    token_fingerprint,
)
from app.config import get_settings
from app.db.redis import get_redis
from app.db.session import SessionDep

router = APIRouter(prefix="/auth", tags=["auth"])

_COOKIE = "refresh_token"


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest, response: Response, session: SessionDep
) -> TokenResponse:
    row = (
        await session.execute(
            text(
                "SELECT id::text, email, password_hash, is_active, is_admin"
                " FROM users WHERE email = :email"
            ),
            {"email": body.email},
        )
    ).fetchone()
    if not row or not verify_password(body.password, row.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    if not row.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Account disabled"
        )

    access = create_access_token(row.id, row.email, is_admin=row.is_admin)
    refresh = create_refresh_token(row.id, row.email)
    s = get_settings()
    response.set_cookie(
        key=_COOKIE,
        value=refresh,
        httponly=True,
        secure=s.app_env == "production",
        samesite="strict",
        max_age=s.jwt_refresh_token_expire_days * 86400,
    )
    return TokenResponse(access_token=access)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    refresh_token: str | None = Cookie(default=None, alias=_COOKIE),
) -> TokenResponse:
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token"
        )
    try:
        payload = decode_token(refresh_token)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    fp = token_fingerprint(refresh_token)
    if await get_redis().exists(f"blocklist:refresh:{fp}"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked"
        )

    return TokenResponse(
        access_token=create_access_token(payload["sub"], payload["email"])
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=_COOKIE),
) -> None:
    if refresh_token:
        try:
            payload = decode_token(refresh_token)
            exp = payload.get("exp", 0)
            ttl = max(int(exp - datetime.now(UTC).timestamp()), 1)
            fp = token_fingerprint(refresh_token)
            await get_redis().setex(f"blocklist:refresh:{fp}", ttl, "1")
        except jwt.PyJWTError:
            pass  # expired token — no need to blocklist, just clear cookie
    response.delete_cookie(key=_COOKIE, httponly=True, samesite="strict")


@router.get("/me", response_model=UserInfo)
async def me(current_user: CurrentUser) -> UserInfo:
    return UserInfo(
        id=current_user["id"],
        email=current_user["email"],
        is_active=True,
        is_admin=current_user.get("is_admin", False),
    )
