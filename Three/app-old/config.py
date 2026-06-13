"""
App configuration. Loads from environment / .env once, app-wide.

This is also what fixes the 'shell vs app' problem you hit earlier: the app
reads the key from .env directly, so it never depends on `export`ing vars
into an interactive shell.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- core ---
    APP_ENV: str = "development"
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --- data stores ---
    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- LLM (kimchi via OpenAI-compatible endpoint) ---
    LLM_PROVIDER: str = "openai"          # openai | mock
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://llm.kimchi.dev/openai/v1"
    LLM_MODEL: str = "kimi-k2.6"
    LLM_JSON_MODE_SUPPORTED: bool = True  # confirmed honored by the gateway

    # --- telegram ---
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""
    PUBLIC_BASE_URL: str = ""

    # --- security / limits ---
    CORS_ALLOWED_ORIGINS: str = "http://localhost:5173"
    RATE_LIMIT_PER_MINUTE: int = 60
    UPLOAD_MAX_MB: int = 15

    # --- feature flags ---
    FLAG_REMINDERS_ENABLED: bool = True
    FLAG_OCR_ENABLED: bool = True
    PROMPT_VERSION: str = "v1"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
