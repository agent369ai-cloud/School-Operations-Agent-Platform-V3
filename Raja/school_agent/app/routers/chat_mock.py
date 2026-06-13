import asyncio
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import AuditEvent
from sse_starlette.sse import EventSourceResponse
import json
import uuid

router = APIRouter()
DASHBOARD_SSE_QUEUE = asyncio.Queue()

class ChatInput(BaseModel):
    student_id: str
    student_name: str
    message: str

@router.post("/webhook")
async def simulate_incoming_chat(payload: ChatInput, request: Request, db: Session = Depends(get_db)):
    """
    Simulates a webhook payload hitting your server from WhatsApp/Telegram.
    """
    student_id = payload.student_id
    student_name = payload.student_name
    message_text = payload.message.lower()
    
    correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    
    # 1. Intent Routing Engine
    if "blocked" in message_text or "stuck" in message_text:
        inferred_intent = "STUDENT_BLOCKED"
        dashboard_status = "BLOCKED"
    elif "done" in message_text or "finished" in message_text or "submit" in message_text:
        inferred_intent = "STUDENT_SUBMISSION"
        dashboard_status = "SUBMITTED"
    else:
        inferred_intent = "PROGRESS_UPDATE"
        dashboard_status = "IN_PROGRESS"
        
    # 2. Audit Trail
    audit_log = AuditEvent(
        correlation_id=correlation_id,
        actor_id=student_id,
        event_type=inferred_intent,
        payload={
            "student_name": student_name,
            "raw_message": payload.message,
            "mapped_status": dashboard_status
        }
    )
    db.add(audit_log)
    db.commit()
    
    # 3. Real-time Queue
    ui_payload = json.dumps({
        "student_id": student_id,
        "student_name": student_name,
        "status": dashboard_status,
        "latest_message": payload.message,
        "correlation_id": correlation_id
    })
    await DASHBOARD_SSE_QUEUE.put(ui_payload)
    
    return {
        "status": "PROCESSED", 
        "intent_routed": inferred_intent, 
        "correlation_id": correlation_id
    }

@router.get("/stream")
async def dashboard_realtime_stream(request: Request):
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            try:
                data = await asyncio.wait_for(DASHBOARD_SSE_QUEUE.get(), timeout=1.0)
                yield {"event": "student_update", "data": data}
            except asyncio.TimeoutError:
                yield {"event": "ping", "data": "keep-alive"}
    return EventSourceResponse(event_generator())

@router.get("/audit-timeline")
async def get_entire_audit_timeline(db: Session = Depends(get_db)):
    events = db.query(AuditEvent).order_by(AuditEvent.created_at.asc()).all()
    timeline = []
    for event in events:
        timeline.append({
            "time": str(event.created_at),
            "workflow_id": event.correlation_id,
            "who": event.actor_id,
            "action": event.event_type,
            "details_captured": event.payload
        })
    return {
        "total_actions_logged": len(timeline),
        "session_replay_timeline": timeline
    }

