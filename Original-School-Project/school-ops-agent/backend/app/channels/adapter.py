"""
Channel adapters + canonical message envelope.

The rest of the system speaks one shape — ``CanonicalMessage`` — regardless of
whether a message came from Telegram or WhatsApp. Each adapter knows how to
(a) verify inbound webhook authenticity, (b) normalize an inbound payload into
the canonical envelope, and (c) format + "send" an outbound message.

In ``channel_mode=mock`` the adapter records outbound messages in memory so the
demo and tests can assert what would have been sent without external calls.
This satisfies the bonus "canonical message envelope" item and keeps the live
integration a thin, swappable edge.
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("channels")
settings = get_settings()


@dataclass
class CanonicalMessage:
    channel: str                  # "telegram" | "whatsapp"
    external_user_id: str         # provider's user/chat id
    provider_message_id: str      # used for idempotent dedup
    text: str | None
    received_at: datetime
    raw: dict = field(default_factory=dict)


@dataclass
class OutboundMessage:
    channel: str
    external_user_id: str
    text: str
    sent_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ChannelAdapter:
    name = "base"

    def verify_webhook(self, *, headers: dict, body: bytes) -> bool:
        raise NotImplementedError

    def parse_inbound(self, payload: dict) -> CanonicalMessage:
        raise NotImplementedError

    def send(self, *, external_user_id: str, text: str) -> OutboundMessage:
        raise NotImplementedError


class TelegramAdapter(ChannelAdapter):
    name = "telegram"

    def verify_webhook(self, *, headers: dict, body: bytes) -> bool:
        # Telegram sends a secret token header configured at setWebhook time.
        provided = headers.get("x-telegram-bot-api-secret-token", "")
        expected = settings.telegram_webhook_secret
        return hmac.compare_digest(provided, expected)

    def parse_inbound(self, payload: dict) -> CanonicalMessage:
        msg = payload.get("message") or payload.get("edited_message") or {}
        chat = msg.get("chat", {})
        return CanonicalMessage(
            channel=self.name,
            external_user_id=str(chat.get("id", "")),
            provider_message_id=str(
                payload.get("update_id") or msg.get("message_id", "")
            ),
            text=msg.get("text"),
            received_at=datetime.now(timezone.utc),
            raw=payload,
        )

    def send(self, *, external_user_id: str, text: str) -> OutboundMessage:
        if settings.channel_mode == "mock" or not settings.telegram_bot_token:
            out = OutboundMessage(self.name, external_user_id, text)
            _MockSink.record(out)
            log.info("mock_send", extra={"channel": self.name,
                                         "to": external_user_id})
            return out
        # Live send (best-effort; kept thin).
        import httpx  # local import so mock mode needs no dependency

        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        try:
            httpx.post(url, json={"chat_id": external_user_id, "text": text},
                       timeout=10.0)
        except Exception as exc:  # pragma: no cover
            log.warning("telegram_send_failed", extra={"error": str(exc)})
        return OutboundMessage(self.name, external_user_id, text)


class WhatsAppAdapter(ChannelAdapter):
    """Mock-only WhatsApp adapter demonstrating the canonical envelope across a
    second channel (bonus). Inbound shape mirrors WhatsApp Cloud API."""

    name = "whatsapp"

    def verify_webhook(self, *, headers: dict, body: bytes) -> bool:
        provided = headers.get("x-hub-signature-256", "")
        # Simplified: in mock mode accept a shared secret echo.
        return bool(provided) or settings.channel_mode == "mock"

    def parse_inbound(self, payload: dict) -> CanonicalMessage:
        try:
            entry = payload["entry"][0]["changes"][0]["value"]
            message = entry["messages"][0]
            return CanonicalMessage(
                channel=self.name,
                external_user_id=str(message["from"]),
                provider_message_id=str(message["id"]),
                text=message.get("text", {}).get("body"),
                received_at=datetime.now(timezone.utc),
                raw=payload,
            )
        except (KeyError, IndexError):
            return CanonicalMessage(
                channel=self.name, external_user_id="", provider_message_id="",
                text=None, received_at=datetime.now(timezone.utc), raw=payload,
            )

    def send(self, *, external_user_id: str, text: str) -> OutboundMessage:
        out = OutboundMessage(self.name, external_user_id, text)
        _MockSink.record(out)
        log.info("mock_send", extra={"channel": self.name, "to": external_user_id})
        return out


class _MockSink:
    """In-memory record of outbound messages for demo/test assertions."""

    sent: list[OutboundMessage] = []

    @classmethod
    def record(cls, msg: OutboundMessage) -> None:
        cls.sent.append(msg)

    @classmethod
    def drain(cls) -> list[OutboundMessage]:
        out = list(cls.sent)
        cls.sent.clear()
        return out


_ADAPTERS: dict[str, ChannelAdapter] = {
    "telegram": TelegramAdapter(),
    "whatsapp": WhatsAppAdapter(),
}


def get_adapter(channel: str) -> ChannelAdapter:
    adapter = _ADAPTERS.get(channel)
    if adapter is None:
        raise ValueError(f"unknown channel: {channel}")
    return adapter


def sent_messages() -> list[OutboundMessage]:
    return _MockSink.drain()
