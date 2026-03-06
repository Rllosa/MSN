from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database & cache — required, no defaults
    database_url: str
    redis_url: str

    # IMAP
    imap_host: str
    imap_port: int = 993
    imap_user: str
    imap_password: str
    imap_poll_interval_seconds: int = 30

    # SMTP
    smtp_host: str
    smtp_port: int = 587
    smtp_user: str
    smtp_password: str
    smtp_from: str

    # WhatsApp
    whatsapp_phone_number_id: str
    whatsapp_access_token: str
    whatsapp_verify_token: str
    whatsapp_app_secret: str
    whatsapp_api_version: str = "v21.0"

    # JWT — jwt_secret_key required, no default
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 30

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    frontend_url: str = "http://localhost:5173"
    web_concurrency: int = 1


@lru_cache
def get_settings() -> Settings:
    return Settings()
