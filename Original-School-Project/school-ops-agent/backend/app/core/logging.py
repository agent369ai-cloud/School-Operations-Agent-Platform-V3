"""
Structured logging with correlation-id propagation.

Every log line is JSON with a `correlation_id` so a single channel->intent->
action->notify flow can be grepped end to end. The correlation id lives in a
ContextVar set by middleware (HTTP) or by the channel dispatcher (chat), so
service code does not have to thread it through every call.

Privacy: helpers here never log raw message bodies or PII by default. Callers
pass already-screened summaries.
"""
from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def set_correlation_id(cid: str | None) -> str:
    cid = cid or new_correlation_id()
    _correlation_id.set(cid)
    return cid


def get_correlation_id() -> str | None:
    return _correlation_id.get()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }
        # Merge structured `extra` fields if present.
        for key, value in getattr(record, "__dict__", {}).items():
            if key in ("args", "msg", "levelname", "name", "exc_info", "exc_text",
                       "stack_info", "lineno", "funcName", "created", "msecs",
                       "relativeCreated", "thread", "threadName", "processName",
                       "process", "pathname", "filename", "module", "levelno"):
                continue
            if key.startswith("_"):
                continue
            if key not in base:
                base[key] = value
        if record.exc_info:
            base["exc"] = self.formatException(record.exc_info)
        return json.dumps(base, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
