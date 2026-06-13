"""
Database engine + session wiring.

`Base` is the declarative base every model inherits from and that Alembic
autogenerate reads metadata from. `get_db` is the FastAPI dependency that
yields a request-scoped session and always closes it.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,   # recover from dropped DB connections gracefully
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine, autoflush=False, expire_on_commit=False, class_=Session
)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
