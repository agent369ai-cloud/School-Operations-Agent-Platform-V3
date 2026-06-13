"""
FastAPI application entrypoint.

Run:  uvicorn app.main:app --reload --port 8000
Docs: http://localhost:8000/docs  (use the Authorize button with a login token)
"""

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.api.routes import auth as auth_routes
from app.api.routes import classes as class_routes
from app.api.routes import invites as invite_routes

app = FastAPI(title="School Operations Agent Platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,   # explicit list, not "*"
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(class_routes.router)
app.include_router(invite_routes.router)


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "db": "ok", "env": settings.APP_ENV}
