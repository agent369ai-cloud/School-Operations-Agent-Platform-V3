"""
Audit service: append-only event recording with privacy screening.

Every important action calls ``record_event``. The audit log is the system's
source of truth for "what happened" and powers the timeline view, so the
brief's requirement that the timeline "explains what happened without
requiring database inspection" is met by writing human-readable summaries here.

Privacy: ``detail`` is screened to drop obvious PII keys before persistence.
Dashboards and timelines render ``summary`` + screened ``detail`` only.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.logging import get_correlation_id, get_logger
from app.models.enums import AuditEventType
from app.models.operations import AuditEvent

log = get_logger("audit")

# Keys we never persist into the audit detail blob.
_PII_KEYS = {"password", "hashed_password", "token", "raw_token", "phone",
             "email", "contact", "guardian_contact", "secret"}


def _screen(detail: dict | None) -> dict | None:
    if not detail:
        return detail
    screened = {}
    for k, v in detail.items():
        if k.lower() in _PII_KEYS:
            screened[k] = "[redacted]"
        elif isinstance(v, dict):
            screened[k] = _screen(v)
        else:
            screened[k] = v
    return screened


def record_event(
    db: Session,
    *,
    event_type: AuditEventType,
    summary: str,
    school_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_label: str | None = None,
    resource_type: str | None = None,
    resource_id: str | uuid.UUID | None = None,
    detail: dict | None = None,
    correlation_id: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        event_type=event_type,
        summary=summary,
        school_id=school_id,
        actor_user_id=actor_user_id,
        actor_label=actor_label,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        detail=_screen(detail),
        correlation_id=correlation_id or get_correlation_id(),
    )
    db.add(event)
    db.flush()  # assign id without committing the surrounding transaction
    log.info(
        "audit_event",
        extra={
            "event_type": getattr(event_type, "value", event_type),
            "summary": summary,
            "resource_type": resource_type,
            "resource_id": str(resource_id) if resource_id else None,
        },
    )
    return event
