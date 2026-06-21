"""
FastAPI application entrypoint.

Wires routers, middleware (correlation id, simple rate limit, CORS), global
exception handling that turns AccessDenied into an audited 403, and the
scheduler lifecycle.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import (
    admin,
    assignments,
    auth,
    channels,
    dashboard,
    documents,
    guardian,
    operations,
)
from app.core.authz import AccessDenied
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger, set_correlation_id
from app.db import base as _db_base
from app.db.base import init_db
from app.models.enums import AuditEventType, StateTransitionError
from app.scheduler.worker import start_scheduler, stop_scheduler
from app.services.audit import record_event

settings = get_settings()
configure_logging("DEBUG" if settings.debug else "INFO")
log = get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # create tables for SQLite/demo; Postgres uses Alembic
    start_scheduler()
    log.info("app_startup", extra={"environment": settings.environment})
    try:
        yield
    finally:
        stop_scheduler()
        log.info("app_shutdown")


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Correlation id middleware ---
@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    cid = request.headers.get("x-correlation-id")
    cid = set_correlation_id(cid)
    response = await call_next(request)
    response.headers["x-correlation-id"] = cid
    return response


# --- Naive in-memory rate limiter (per client IP) ---
_hits: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client = request.client.host if request.client else "unknown"
    now = time.time()
    window = _hits[client]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= settings.rate_limit_per_minute:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "rate limit exceeded"},
        )
    window.append(now)
    return await call_next(request)


# --- Exception handlers ---
@app.exception_handler(AccessDenied)
async def access_denied_handler(request: Request, exc: AccessDenied):
    # Audit every denial so wrong-context attempts appear in the timeline.
    from app.core.security import decode_access_token
    import uuid as _uuid
    school_id = None
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        payload = decode_access_token(auth.split(" ", 1)[1])
        if payload and payload.get("school_id"):
            try:
                school_id = _uuid.UUID(payload["school_id"])
            except (ValueError, AttributeError):
                pass
    db = _db_base.SessionLocal()
    try:
        record_event(
            db, event_type=AuditEventType.ACCESS_DENIED,
            summary=f"Access denied: {exc.reason}",
            school_id=school_id, actor_label="http", resource_type="route",
            resource_id=str(request.url.path), detail=exc.detail,
        )
        db.commit()
    except Exception:  # pragma: no cover
        db.rollback()
    finally:
        db.close()
    return JSONResponse(status_code=status.HTTP_403_FORBIDDEN,
                        content={"detail": exc.reason})


@app.exception_handler(StateTransitionError)
async def state_error_handler(request: Request, exc: StateTransitionError):
    return JSONResponse(status_code=status.HTTP_409_CONFLICT,
                        content={"detail": str(exc)})


@app.get("/health")
def health():
    return {"status": "ok", "llm_live": settings.is_live_llm,
            "db": "sqlite" if settings.is_sqlite else "postgres"}


for r in (auth.router, admin.router, documents.router, assignments.router,
          operations.router, channels.router, dashboard.router, guardian.router):
    app.include_router(r, prefix="/api")
