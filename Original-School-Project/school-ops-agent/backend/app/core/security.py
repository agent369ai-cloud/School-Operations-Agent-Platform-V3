"""
Security primitives: password hashing, JWT issue/verify, and token hashing.

We use:
  * bcrypt (via passlib) for password hashing.
  * python-jose for JWTs.
  * SHA-256 for hashing invite tokens and idempotency keys (these are
    high-entropy random tokens, so a fast hash is appropriate and lets us
    index/look them up).

Everything here is pure and side-effect free so it is trivially testable.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt as _bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings

settings = get_settings()


# --- Passwords ---------------------------------------------------------------
def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# --- JWT ---------------------------------------------------------------------
def create_access_token(
    *, subject: str, role: str, school_id: str, extra: dict[str, Any] | None = None
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "school_id": school_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
        "typ": "access",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.jwt_algorithm]
        )
    except JWTError:
        return None
    if payload.get("typ") != "access":
        return None
    return payload


# --- High-entropy tokens (invites) + hashing --------------------------------
def generate_invite_token() -> str:
    """A URL-safe random token shown to the user exactly once."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 hex digest, used to store invite tokens and derive idempotency
    keys. Constant-length, indexable, not reversible."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
