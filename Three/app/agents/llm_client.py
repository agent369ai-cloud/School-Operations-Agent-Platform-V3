"""
LLM client for the School Operations Agent Platform.

Talks to any OpenAI-compatible endpoint (kimchi.dev) using values from app.config,
so the API key/base-url/model come from .env via pydantic-settings -- NOT from the
shell environment. This is the version to run under uvicorn.

Design rule: the model only ever PROPOSES. Business code calls `complete_structured`,
which forces the reply into a Pydantic schema (with one repair retry) before anything
downstream sees it.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Type, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import settings

log = logging.getLogger("llm")

T = TypeVar("T", bound=BaseModel)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class LLMError(Exception):
    """Raised when the provider call fails outright (network/auth/5xx)."""


def _get_client():
    if settings.LLM_PROVIDER == "mock":
        return None
    from openai import OpenAI  # lazy import so mock/tests need no SDK
    return OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)


def chat(messages: list[dict], *, json_mode: bool = False, **kwargs) -> str:
    """One raw chat call. Returns message.content (stripped); ignores reasoning_content."""
    if settings.LLM_PROVIDER == "mock":
        return _mock_response(messages)

    client = _get_client()
    params: dict[str, Any] = {
        "model": settings.LLM_MODEL,
        "messages": messages,
        "temperature": kwargs.pop("temperature", 0),
    }
    if json_mode and settings.LLM_JSON_MODE_SUPPORTED:
        params["response_format"] = {"type": "json_object"}
    params.update(kwargs)

    try:
        resp = client.chat.completions.create(**params)
    except Exception as e:  # noqa: BLE001 -- normalize SDK/network errors
        raise LLMError(str(e)) from e

    return (resp.choices[0].message.content or "").strip()


def complete_structured(messages: list[dict], schema: Type[T], *, max_retries: int = 1) -> T:
    """Call the model and coerce the reply into `schema`, with one repair retry."""
    work = list(messages)
    last_err = ""

    for attempt in range(max_retries + 1):
        raw = chat(work, json_mode=True)
        cleaned = _FENCE.sub("", raw).strip()
        try:
            data = json.loads(cleaned)
            return schema.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            last_err = str(e)
            log.warning("structured parse failed (attempt %d): %s", attempt + 1, last_err)
            work = messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": (
                    "That was not valid against the required schema. "
                    f"Error: {last_err}. Return ONLY corrected JSON, no prose."
                )},
            ]

    raise LLMError(f"could not produce valid {schema.__name__}: {last_err}")


def _mock_response(messages: list[dict]) -> str:
    """Deterministic canned output for tests / offline runs."""
    last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "").lower()
    if "extract" in last:  # assignment-parse shape
        return json.dumps({
            "title": "Fractions Worksheet",
            "subject": "Math",
            "instructions": "Complete questions 1-10.",
            "due_date": None,
            "target_hint": "whole class",
            "ambiguities": ["No due date was specified. When is it due?"],
            "confidence": 0.6,
        })
    if "blocked" in last or "stuck" in last:
        return '{"intent": "blocked", "confidence": 0.9}'
    return '{"intent": "unknown", "confidence": 0.3}'
