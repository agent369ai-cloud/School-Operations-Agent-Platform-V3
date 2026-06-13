"""
Invite token helpers.

The raw token is shown to the inviter exactly once and never stored. We persist
only its SHA-256 hash, so a leaked database row can't be used to accept invites.
Tokens are single-use (Invite.used_at) and short-lived (Invite.expires_at).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone


def generate_invite_token() -> tuple[str, str]:
    """Return (raw_token, token_hash). Store the hash; hand the raw to the user."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def default_expiry(hours: int = 72) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)
