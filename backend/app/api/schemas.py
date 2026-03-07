from __future__ import annotations

from datetime import datetime

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
    is_admin: bool


class AdminUserInfo(BaseModel):
    id: str
    email: str
    is_active: bool
    is_admin: bool
    created_at: datetime


class CreateUserRequest(BaseModel):
    email: str
    password: str
    is_admin: bool = False


class UpdateUserRequest(BaseModel):
    password: str | None = None
    is_admin: bool | None = None
    is_active: bool | None = None
