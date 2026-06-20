"""
Pydantic schemas for model (LLM) structured outputs.

These are the contract between the model and the rest of the system. Model
output is parsed into one of these models; if validation fails the output is
rejected (treated as a model failure), never written to domain tables. This is
the concrete mechanism behind "treat LLM output as proposed action until
validated/approved".
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.enums import IntentType


class IntentResult(BaseModel):
    intent: IntentType
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("intent", mode="before")
    @classmethod
    def _coerce_unknown(cls, v):
        # Any value the model invents that isn't a known intent becomes UNKNOWN.
        try:
            IntentType(v)
            return v
        except ValueError:
            return IntentType.UNKNOWN.value


class ParsedAssignment(BaseModel):
    title: str = ""
    subject: str | None = None
    instructions: str = ""
    due_at: datetime | None = None
    ambiguities: list[str] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @property
    def needs_clarification(self) -> bool:
        return bool(self.clarifying_questions) or not self.title


class RosterRow(BaseModel):
    name: str
    klass: str | None = Field(default=None, alias="class")
    guardian_contact: str | None = None

    model_config = {"populate_by_name": True}


class ParsedRoster(BaseModel):
    rows: list[RosterRow] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @property
    def needs_clarification(self) -> bool:
        return bool(self.clarifying_questions)


# JSON schemas handed to OpenAI structured-outputs / used as documentation.
INTENT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": [i.value for i in IntentType]},
        "confidence": {"type": "number"},
    },
    "required": ["intent", "confidence"],
    "additionalProperties": False,
}

ASSIGNMENT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "subject": {"type": ["string", "null"]},
        "instructions": {"type": "string"},
        "due_at": {"type": ["string", "null"]},
        "ambiguities": {"type": "array", "items": {"type": "string"}},
        "clarifying_questions": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": ["title", "instructions", "ambiguities", "clarifying_questions",
                 "confidence"],
    "additionalProperties": False,
}

ROSTER_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "class": {"type": ["string", "null"]},
                    "guardian_contact": {"type": ["string", "null"]},
                },
                "required": ["name"],
            },
        },
        "ambiguities": {"type": "array", "items": {"type": "string"}},
        "clarifying_questions": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": ["rows", "ambiguities", "clarifying_questions", "confidence"],
    "additionalProperties": False,
}
