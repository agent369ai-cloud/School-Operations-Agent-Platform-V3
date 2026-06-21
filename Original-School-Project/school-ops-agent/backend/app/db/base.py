"""
Database engine, session management, and DB-portable column types.

Design goal: the same ORM models run unchanged on SQLite (zero-setup local
demo + deterministic tests) and PostgreSQL (production-shaped). We achieve
this with two custom TypeDecorators:

  * GUID  - stores UUIDs as native uuid on Postgres, CHAR(36) on SQLite.
  * JSONB - uses postgres JSONB when available, falls back to generic JSON.

This avoids SQLite-only tricks leaking into the schema, which keeps the
code honest about being production-shaped.
"""
from __future__ import annotations

import uuid
from collections.abc import Generator

from sqlalchemy import CHAR, create_engine, types
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import JSON, TypeDecorator

from app.core.config import get_settings

settings = get_settings()


class GUID(TypeDecorator):
    """Platform-independent UUID type.

    Uses PostgreSQL's native UUID, otherwise stores as stringified hex.
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return str(value if isinstance(value, uuid.UUID) else uuid.UUID(str(value)))

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if not isinstance(value, uuid.UUID):
            return uuid.UUID(str(value))
        return value


class PortableJSON(TypeDecorator):
    """JSONB on Postgres, generic JSON elsewhere."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class Base(DeclarativeBase):
    type_annotation_map = {
        dict: PortableJSON,
        list: PortableJSON,
    }


def _make_engine():
    connect_args = {}
    if settings.is_sqlite:
        # check_same_thread=False is required because the scheduler thread and
        # request threads share the engine. We rely on short-lived sessions.
        connect_args = {"check_same_thread": False}
    engine = create_engine(
        settings.database_url,
        connect_args=connect_args,
        pool_pre_ping=True,
        echo=False,
        future=True,
    )
    # Enforce foreign keys on SQLite (off by default), so our cross-tenant
    # FK constraints actually bite during local demos and tests.
    if settings.is_sqlite:
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def _fk_pragma(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


engine = _make_engine()
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: a request-scoped session that always closes."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Used for SQLite demo + tests.

    In a Postgres deployment you would run Alembic migrations instead;
    see migrations/README for the intended workflow.
    """
    from app import models  # noqa: F401  (ensures models are registered)

    Base.metadata.create_all(bind=engine)

    # Additive column migrations for SQLite (create_all won't ALTER existing tables).
    if settings.is_sqlite:
        _sqlite_add_columns_if_missing()


def _sqlite_add_columns_if_missing() -> None:
    """Apply any missing columns to existing SQLite tables."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    migrations = [
        ("assignment_targets", "teacher_note", "TEXT"),
        ("submissions", "ai_review", "JSON"),
    ]
    with engine.connect() as conn:
        for table, column, col_type in migrations:
            existing = [c["name"] for c in inspector.get_columns(table)]
            if column not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
        conn.commit()
