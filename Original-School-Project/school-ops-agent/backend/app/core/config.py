"""
Application configuration.

All configuration is environment-driven. No secrets are committed to git.
See `.env.example` for the full set of supported variables.

The settings object is constructed once at import time and injected
everywhere via `get_settings()` so tests can override it cleanly.
"""
from __future__ import annotations

import functools
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Core ---
    app_name: str = "School Operations Agent Platform"
    environment: Literal["local", "test", "staging", "production"] = "local"
    debug: bool = True

    # --- Database ---
    # Default is a local SQLite file so the project runs on a fresh clone
    # with zero external provisioning. Set DATABASE_URL to a postgresql://
    # DSN to run production-shaped. Models are written DB-portable.
    database_url: str = "sqlite:///./school_ops.db"

    # --- Auth ---
    # SECRET_KEY MUST be overridden in any non-local environment.
    secret_key: str = "dev-only-insecure-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 480  # 8 hours for development
    # Scoped invite links / codes are deliberately short-lived.
    invite_token_ttl_hours: int = 72

    # --- LLM ---
    # Mode controls whether we call a live model or the deterministic mock.
    # "auto" uses live if a key is present, else falls back to mock.
    llm_mode: Literal["auto", "live", "mock"] = "auto"
    llm_provider: Literal["gemini", "groq"] = "gemini"
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    groq_model: str = "llama-3.3-70b-versatile"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2

    # --- Channels ---
    telegram_bot_token: str | None = None
    # Shared secret used to verify inbound webhook authenticity.
    telegram_webhook_secret: str = "dev-webhook-secret"
    channel_mode: Literal["mock", "live"] = "mock"

    # --- CORS ---
    # Stored as a comma-separated string so pydantic-settings never tries to
    # JSON-parse it (which fails for plain URLs like https://foo.onrender.com).
    cors_origins: str = "http://localhost:3000"

    # --- Rate limiting ---
    rate_limit_per_minute: int = 120

    # --- Scheduler ---
    scheduler_tick_seconds: int = 30

    # --- Uploads ---
    upload_dir: str = "./uploads"
    max_upload_bytes: int = 10 * 1024 * 1024  # 10 MiB
    allowed_upload_extensions: str = ".pdf,.docx,.csv,.txt,.png,.jpg,.jpeg"

    @field_validator("database_url", mode="before")
    @classmethod
    def _fix_postgres_url(cls, v):
        # Render provides postgres:// or postgresql:// — SQLAlchemy needs the
        # psycopg3 dialect prefix so it doesn't fall back to psycopg2.
        if isinstance(v, str):
            if v.startswith("postgres://"):
                return v.replace("postgres://", "postgresql+psycopg://", 1)
            if v.startswith("postgresql://") and "+psycopg" not in v:
                return v.replace("postgresql://", "postgresql+psycopg://", 1)
        return v

    @staticmethod
    def _parse_str_list(v: str) -> list[str]:
        """Parse a comma-separated string or JSON array into a list."""
        import json
        v = v.strip()
        if v.startswith("["):
            try:
                return json.loads(v)
            except Exception:
                pass
        return [item.strip() for item in v.split(",") if item.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        return self._parse_str_list(self.cors_origins)

    @property
    def allowed_upload_extensions_list(self) -> list[str]:
        return self._parse_str_list(self.allowed_upload_extensions)

    @property
    def is_live_llm(self) -> bool:
        if self.llm_mode == "live":
            return True
        if self.llm_mode == "mock":
            return False
        # auto
        if self.llm_provider == "gemini":
            return bool(self.gemini_api_key)
        return bool(self.groq_api_key)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()
