from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from app.auth.tokens import decode_token

_bearer = HTTPBearer()


async def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> dict:
    try:
        payload = decode_token(creds.credentials)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
    return {"id": payload["sub"], "email": payload["email"]}


CurrentUser = Annotated[dict, Depends(get_current_user)]
