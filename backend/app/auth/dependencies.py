from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text

from app.auth.tokens import decode_token
from app.db.session import SessionDep

_bearer = HTTPBearer()


async def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> dict:
    try:
        payload = decode_token(creds.credentials)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
    return {
        "id": payload["sub"],
        "email": payload["email"],
        "is_admin": payload.get("is_admin", False),
    }


CurrentUser = Annotated[dict, Depends(get_current_user)]


async def get_current_admin(
    current_user: Annotated[dict, Depends(get_current_user)],
    session: SessionDep,
) -> dict:
    """Re-validates is_admin from DB on every admin request.

    Prevents stale token abuse when admin status is revoked.
    """
    row = (
        await session.execute(
            text("SELECT is_admin FROM users WHERE id = :id"),
            {"id": current_user["id"]},
        )
    ).fetchone()
    if not row or not row.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    return current_user


AdminUser = Annotated[dict, Depends(get_current_admin)]
