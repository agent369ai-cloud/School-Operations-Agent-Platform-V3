# app/config.py
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "missing-key")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./school.db")


    llm_provider: str = os.getenv("llm_provider", "openai")
    openai_base_url: str = os.getenv("openai_base_url", "https://kimchi.dev")
    llm_model: str = os.getenv("llm_model", "gpt-4o-mini")
    secret_key: str = os.getenv("secret_key", "default-secret")


    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
