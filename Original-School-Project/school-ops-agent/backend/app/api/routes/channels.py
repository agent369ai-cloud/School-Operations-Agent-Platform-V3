"""Channel webhook routes (Telegram / WhatsApp)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.channels.adapter import get_adapter
from app.channels.dispatch import handle_inbound
from app.db.base import SessionLocal

router = APIRouter(prefix="/channels", tags=["channels"])


@router.post("/{channel}/webhook")
async def channel_webhook(channel: str, request: Request):
    try:
        adapter = get_adapter(channel)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown channel")

    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    if not adapter.verify_webhook(headers=headers, body=body):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid webhook signature")

    payload = await request.json()
    msg = adapter.parse_inbound(payload)
    if not msg.external_user_id or not msg.provider_message_id:
        # Acknowledge non-message updates (e.g. delivery receipts) without work.
        return {"status": "ignored"}

    db: Session = SessionLocal()
    try:
        reply = handle_inbound(db, msg)
        return {"status": "ok", "reply": reply}
    finally:
        db.close()
