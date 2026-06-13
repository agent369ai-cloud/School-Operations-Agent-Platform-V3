"""
Audit writer. Append-only: never update or delete an AuditEvent.

Keep PII out of `payload` -- store ids and enums, not student names or message
bodies. The dashboard timeline reads these so operators can explain what
happened without inspecting the database.

Usage (within an existing transaction; caller commits):
    record(db, action="assignment.approved", school_id=..., actor_user_id=...,
           resource_type="assignment", resource_id=assignment.id,
           correlation_id=cid, payload={"targets": 2})
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import AuditEvent


def record(
    db: Session,
    *,
    action: str,
    school_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,   # None == system / agent
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    correlation_id: str | None = None,
    payload: dict | None = None,
) -> AuditEvent:
    ev = AuditEvent(
        action=action,
        school_id=school_id,
        actor_user_id=actor_user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        correlation_id=correlation_id,
        payload=payload,
    )
    db.add(ev)
    db.flush()  # assign id without forcing a full commit
    return ev
