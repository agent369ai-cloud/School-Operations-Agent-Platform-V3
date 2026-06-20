"""
In-process event bus for live dashboard updates via Server-Sent Events.

Scope: events are published per-school. A dashboard subscribes with its
school_id and receives only that school's events — never another tenant's,
matching the isolation guarantee of the rest of the system.

This is intentionally in-process (asyncio.Queue per subscriber). For multi-
instance deployment you would swap this for Redis pub/sub behind the same
``publish`` / ``subscribe`` interface; the API layer would not change. That
trade-off is documented in the README.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Event:
    type: str
    school_id: str
    payload: dict
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_sse(self) -> str:
        data = json.dumps(
            {"type": self.type, "payload": self.payload, "at": self.at}
        )
        return f"event: {self.type}\ndata: {data}\n\n"


class EventBus:
    def __init__(self) -> None:
        # school_id -> set of subscriber queues
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, school_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subs[school_id].add(q)
        return q

    async def unsubscribe(self, school_id: str, q: asyncio.Queue) -> None:
        async with self._lock:
            self._subs[school_id].discard(q)

    async def publish(self, event: Event) -> None:
        async with self._lock:
            queues = list(self._subs.get(event.school_id, set()))
        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Drop for a slow consumer rather than blocking publishers.
                pass

    def publish_threadsafe(self, event: Event, loop: asyncio.AbstractEventLoop) -> None:
        """Called from the synchronous scheduler thread."""
        asyncio.run_coroutine_threadsafe(self.publish(event), loop)


bus = EventBus()
