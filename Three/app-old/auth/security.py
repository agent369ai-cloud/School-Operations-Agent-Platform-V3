"""
Security primitives: password hashing (bcrypt) and JWT tokens (HS256).

Tokens carry the minimum needed for authorization decisions:
  sub  = user id
  role = UserRole
  sid  = school id  (so we can scope without a DB hit on every request)
  type = access | refresh
Resource-level scope is still checked against the DB in deps.py -- the token
is a claim, not proof of access to a specific row.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings

ALGORITHM = "HS256"


# --- passwords ---

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


# --- tokens ---

def _encode(payload: dict, expires: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {**payload, "iat": now, "exp": now + expires}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(user_id: uuid.UUID, role: str, school_id: uuid.UUID) -> str:
    return _encode(
        {"sub": str(user_id), "role": role, "sid": str(school_id), "type": "access"},
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(user_id: uuid.UUID) -> str:
    return _encode(
        {"sub": str(user_id), "type": "refresh"},
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str) -> dict:
    """Raises jwt.InvalidTokenError (incl. ExpiredSignatureError) on failure."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
