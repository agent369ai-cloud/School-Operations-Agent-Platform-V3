"""
LLM client: Gemini (primary) and Groq (secondary) providers.

Exposes one method — structured(system, user, schema) — that always returns
a dict validated as JSON, or raises ModelError. Three modes:
  live   → always call the real provider
  mock   → deterministic rule-based stand-in (no API call, offline-safe)
  auto   → live if an API key is present, else mock

Prompt-injection posture: document/user text is always passed inside a
delimited block and the system prompt explicitly marks it as untrusted data.
"""
from __future__ import annotations

import json
import time
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("llm")
settings = get_settings()


class ModelError(Exception):
    """Raised when the model cannot produce valid structured output."""


class LLMClient:
    def __init__(self) -> None:
        self.mode_live = settings.is_live_llm
        self.provider = settings.llm_provider
        self._client = None
        if self.mode_live:
            self._init_live()

    def _init_live(self) -> None:
        try:
            if self.provider == "gemini":
                from google import genai
                self._client = genai.Client(api_key=settings.gemini_api_key)
            else:  # groq
                from groq import Groq
                self._client = Groq(api_key=settings.groq_api_key)
        except Exception as exc:
            log.warning("llm_live_init_failed_falling_back_to_mock",
                        extra={"error": str(exc)})
            self.mode_live = False

    # -- Public API -----------------------------------------------------------
    def structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        schema_name: str = "result",
    ) -> dict[str, Any]:
        """Return a dict guaranteed to be JSON-parseable. Retries on transient
        failures; raises ModelError if all attempts are exhausted."""
        last_err: Exception | None = None
        for attempt in range(settings.llm_max_retries + 1):
            try:
                if self.mode_live:
                    raw = self._call_live(system, user, schema, schema_name)
                else:
                    raw = self._call_mock(system, user, schema, schema_name)
                return self._parse_json(raw)
            except Exception as exc:
                last_err = exc
                log.warning("llm_attempt_failed",
                            extra={"attempt": attempt, "error": str(exc)})
                time.sleep(min(2 ** attempt * 0.2, 2.0))
        raise ModelError(f"structured generation failed: {last_err}")

    # -- Live providers -------------------------------------------------------
    def _call_live(self, system: str, user: str, schema, schema_name) -> str:
        if self.provider == "gemini":
            return self._call_gemini(system, user)
        return self._call_groq(system, user)

    def _call_gemini(self, system: str, user: str) -> str:
        from google.genai import types
        response = self._client.models.generate_content(
            model=settings.gemini_model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system + "\n\nRespond with ONLY a single JSON object, no prose.",
                temperature=0.1,
                max_output_tokens=1500,
            ),
        )
        return response.text or "{}"

    def _call_groq(self, system: str, user: str) -> str:
        resp = self._client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": system + "\n\nRespond with ONLY a single JSON object, no prose."},
                {"role": "user", "content": user},
            ],
            temperature=0.1,
            max_tokens=1500,
        )
        return resp.choices[0].message.content or "{}"

    # -- Deterministic mock ---------------------------------------------------
    def _call_mock(self, system: str, user: str, schema, schema_name) -> str:
        from app.services.mock_llm import generate_mock
        return generate_mock(schema_name=schema_name, user_text=user)

    # -- Helpers --------------------------------------------------------------
    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        raw = raw.strip()
        # Strip markdown fences if the model added them.
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip().rstrip("`").strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ModelError(f"model did not return valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ModelError("model returned non-object JSON")
        return data


_client_singleton: LLMClient | None = None


def get_llm() -> LLMClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = LLMClient()
    return _client_singleton
