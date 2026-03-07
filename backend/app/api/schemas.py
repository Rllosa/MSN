from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserInfo(BaseModel):
    id: str
    email: str
    is_active: bool
