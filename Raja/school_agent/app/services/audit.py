# app/services/audit.py
import uuid
from fastapi import Request
from sqlalchemy.orm import Session
from app.models import AuditEvent

async def log_audit_event(
    db: Session, 
    request: Request, 
    event_type: str, 
    actor_id: str, 
    payload: dict
):
    # Pull the correlation ID generated at the start of the request chain
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    
    event = AuditEvent(
        correlation_id=correlation_id,
        event_type=event_type,
        actor_id=actor_id,
        payload=payload
    )
    db.add(event)
    db.commit()
