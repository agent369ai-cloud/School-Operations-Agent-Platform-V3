"""
Shared test fixtures.

Uses an isolated SQLite database per test session and a FastAPI TestClient.
LLM_MODE is forced to 'mock' so tests are deterministic and offline.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("LLM_MODE", "mock")
os.environ.setdefault("CHANNEL_MODE", "mock")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_school_ops.db")
os.environ.setdefault("SECRET_KEY", "test-secret")


@pytest.fixture(scope="function")
def client(tmp_path, monkeypatch):
    # Fresh DB file per test for isolation.
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")

    # Reset cached settings so the new DATABASE_URL takes effect.
    from app.core import config as config_mod
    config_mod.get_settings.cache_clear()

    # Patch the engine/sessionmaker in-place so all models (registered on the
    # original Base) stay intact and init_db creates every table.
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from app.db import base as base_mod

    new_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
        future=True,
    )

    @event.listens_for(new_engine, "connect")
    def _fk_pragma(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    base_mod.engine = new_engine
    base_mod.SessionLocal = sessionmaker(
        bind=new_engine, autoflush=False, autocommit=False,
        expire_on_commit=False, future=True,
    )

    from app import models  # noqa: F401  ensure all models are registered
    base_mod.init_db()

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def registered_admin(client):
    resp = client.post("/api/auth/register", json={
        "school_name": "Test School", "admin_name": "Admin One",
        "admin_email": "admin@test.edu", "admin_password": "Password123!",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
