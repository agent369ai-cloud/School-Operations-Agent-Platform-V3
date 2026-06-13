"""
LLM client for the School Operations Agent Platform.

Talks to any OpenAI-compatible endpoint. For kimchi.dev set:
    LLM_PROVIDER=openai
    OPENAI_API_KEY=<your kimchi key>
    OPENAI_BASE_URL=https://llm.kimchi.dev/openai/v1
    LLM_MODEL=kimi-k2.6

Design rule for this project: the model only ever PROPOSES. Every call that
matters goes through `complete_structured`, which forces the raw text into a
Pydantic schema (with one repair retry) before any business code sees it.
A junior can add a new structured call by defining a Pydantic model and passing
it in -- they never parse raw model text by hand.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Type, TypeVar

from pydantic import BaseModel, ValidationError

# from app.config import settings   # uncomment in your project
# Minimal stand-in so this file runs on its own for the probe:
import os


class _Settings:
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://llm.kimchi.dev/openai/v1")
    LLM_MODEL = os.getenv("LLM_MODEL", "kimi-k2.6")
    # Set to False once you've confirmed the gateway honors response_format.
    LLM_JSON_MODE_SUPPORTED = os.getenv("LLM_JSON_MODE_SUPPORTED", "true") == "true"


settings = _Settings()
log = logging.getLogger("llm")

T = TypeVar("T", bound=BaseModel)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class LLMError(Exception):
    """Raised when the provider call fails outright (network/auth/5xx)."""


# --- client construction --------------------------------------------------

def _get_client():
    """Return an OpenAI-compatible client. 'mock' short-circuits in tests."""
    if settings.LLM_PROVIDER == "mock":
        return None
    from openai import OpenAI  # imported lazily so mock/tests need no SDK

    return OpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
    )


def chat(messages: list[dict], *, json_mode: bool = False, **kwargs) -> str:
    """
    One raw chat call. Returns message.content (stripped).

    NOTE: kimi-k2.6 returns chain-of-thought in `reasoning_content`; we
    deliberately ignore that and read only `message.content`.
    """
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

    content = (resp.choices[0].message.content or "").strip()
    return content


# --- structured output (the path business code should use) ----------------

def complete_structured(
    messages: list[dict],
    schema: Type[T],
    *,
    max_retries: int = 1,
) -> T:
    """
    Call the model and coerce the reply into `schema`.

    Works whether or not the gateway honors response_format:
      - asks for JSON in both the request and (as a backstop) the prompt
      - strips ```json fences if the model adds them
      - on invalid JSON / schema mismatch, retries once with the error fed back
    Raises LLMError if it still can't produce valid output -- callers should
    map that to an 'unknown / please rephrase' fallback, never a guess.
    """
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
            # Feed the failure back so the model can repair its own output.
            work = messages + [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        "That was not valid against the required schema. "
                        f"Error: {last_err}. Return ONLY corrected JSON, no prose."
                    ),
                },
            ]

    raise LLMError(f"could not produce valid {schema.__name__}: {last_err}")


# --- mock for tests / offline runs ----------------------------------------

def _mock_response(messages: list[dict]) -> str:
    """Deterministic canned output keyed off the last user message."""
    last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    low = last.lower()
    if "blocked" in low or "stuck" in low:
        return '{"intent": "blocked", "confidence": 0.9}'
    if "done" in low or "submit" in low:
        return '{"intent": "submission", "confidence": 0.8}'
    return '{"intent": "unknown", "confidence": 0.3}'


# --- run this file directly to smoke-test against kimchi ------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    class IntentResult(BaseModel):
        intent: str
        confidence: float

    msgs = [
        {"role": "system", "content": "You output only valid JSON. No prose, no markdown."},
        {
            "role": "user",
            "content": (
                'Classify and return {"intent":"...","confidence":0.0}. '
                "Allowed: progress_update, blocked, submission, unknown. "
                "Message: I cant finish, Im stuck on question 3."
            ),
        },
    ]
    print("plain chat ->", chat([{"role": "user", "content": "Reply with one word: pong"}]))
    print("structured ->", complete_structured(msgs, IntentResult))
