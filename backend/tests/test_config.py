"""Unit tests for app.config.Settings."""

from __future__ import annotations

import pytest

from app.config import get_settings

REQUIRED_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db",
    "REDIS_URL": "redis://localhost:6379/0",
    "BEDS24_REFRESH_TOKEN": "test-refresh-token",
    "IMAP_HOST": "imap.example.com",
    "IMAP_USER": "user@example.com",
    "IMAP_PASSWORD": "secret",
    "SMTP_HOST": "smtp.example.com",
    "SMTP_USER": "user@example.com",
    "SMTP_PASSWORD": "secret",
    "SMTP_FROM": "user@example.com",
    "WHATSAPP_PHONE_NUMBER_ID": "12345",
    "WHATSAPP_ACCESS_TOKEN": "token",
    "WHATSAPP_VERIFY_TOKEN": "verify",
    "WHATSAPP_APP_SECRET": "appsecret",
    "JWT_SECRET_KEY": "supersecretkey",
}


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_loads_required_vars(monkeypatch):
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
    s = get_settings()
    assert s.database_url == REQUIRED_ENV["DATABASE_URL"]
    assert s.jwt_secret_key == REQUIRED_ENV["JWT_SECRET_KEY"]
    assert s.imap_host == REQUIRED_ENV["IMAP_HOST"]


def test_defaults(monkeypatch):
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
    s = get_settings()
    assert s.beds24_poll_interval_seconds == 60
    assert s.imap_port == 993
    assert s.imap_poll_interval_seconds == 30
    assert s.smtp_port == 587
    assert s.whatsapp_api_version == "v21.0"
    assert s.jwt_algorithm == "HS256"
    assert s.jwt_access_token_expire_minutes == 60
    assert s.jwt_refresh_token_expire_days == 30
    assert s.app_env == "development"
    assert s.log_level == "INFO"
    assert s.frontend_url == "http://localhost:5173"
    assert s.web_concurrency == 1


def test_missing_required_var_raises(monkeypatch):
    from pydantic import ValidationError

    for k, v in REQUIRED_ENV.items():
        if k != "JWT_SECRET_KEY":
            monkeypatch.setenv(k, v)
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        get_settings()


def test_extra_vars_ignored(monkeypatch):
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("POSTGRES_USER", "msn")
    monkeypatch.setenv("POSTGRES_PASSWORD", "msn")
    # Should not raise despite extra vars
    s = get_settings()
    assert s.database_url is not None
