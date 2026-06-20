"""
Idempotency layer.

Three sources of duplicate work the brief calls out explicitly:
  * webhook retries (provider redelivers the same chat message)
  * double form submits (user double-clicks "create assignment")
  * repeated file uploads (same bytes uploaded twice)

We handle them with one mechanism: a unique ``(scope, key)`` row. The first
caller for a key inserts a row and runs the work; later callers find the row
and replay the stored response instead of re-running the side effect.

For chat webhooks the natural key is the provider message id (stored on
InboundMessage with a unique constraint). For file uploads the key is the
SHA-256 of the bytes. For form submits the client sends an Idempotency-Key
header. All converge here.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.operations import IdempotencyKey


@dataclass
class IdempotencyResult:
    is_replay: bool
    record: IdempotencyKey


def begin(db: Session, *, scope: str, key: str) -> IdempotencyResult:
    """Claim an idempotency key.

    Returns is_replay=True with the prior record if this key was already
    processed; otherwise inserts a placeholder row and returns is_replay=False.

    The unique constraint on (scope, key) makes this race-safe: if two requests
    insert concurrently, one wins and the other catches IntegrityError and is
    treated as a replay.
    """
    existing = (
        db.query(IdempotencyKey)
        .filter(IdempotencyKey.scope == scope, IdempotencyKey.key == key)
        .one_or_none()
    )
    if existing is not None:
        return IdempotencyResult(is_replay=True, record=existing)

    record = IdempotencyKey(scope=scope, key=key, response=None, status_code=0)
    db.add(record)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(IdempotencyKey)
            .filter(IdempotencyKey.scope == scope, IdempotencyKey.key == key)
            .one()
        )
        return IdempotencyResult(is_replay=True, record=existing)

    return IdempotencyResult(is_replay=False, record=record)


def complete(
    db: Session, record: IdempotencyKey, *, response: dict, status_code: int = 200
) -> None:
    """Store the result so future replays return it."""
    record.response = response
    record.status_code = status_code
    db.add(record)
    db.flush()
