"""
Document parsing pipeline.

Ties together extraction -> injection guard -> model structured output ->
pydantic validation -> review-state decision. The output is always a
persisted-ready dict plus a ReviewState, never a direct domain mutation: the
caller stores it on the Document and a human approves before any assignment or
roster import is committed.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.logging import get_logger
from app.models.enums import DocumentType, ReviewState
from app.parsers.injection import (
    SYSTEM_GUARD,
    scan_for_injection,
    wrap_untrusted,
)
from app.schemas.parsing import (
    ASSIGNMENT_JSON_SCHEMA,
    ROSTER_JSON_SCHEMA,
    ParsedAssignment,
    ParsedRoster,
)
from app.services.llm import ModelError, get_llm

log = get_logger("parser")


@dataclass
class ParseOutcome:
    review_state: ReviewState
    parsed: dict
    confidence: float
    ambiguities: list[str]
    clarifying_questions: list[str]


def _finalize(model_obj, injection_notes: list[str]) -> ParseOutcome:
    ambiguities = list(model_obj.ambiguities) + injection_notes
    questions = list(model_obj.clarifying_questions)
    # Injection markers force a human review even if fields are complete.
    needs = bool(questions) or bool(injection_notes) or model_obj.needs_clarification
    state = ReviewState.NEEDS_CLARIFICATION if needs else ReviewState.PARSED
    return ParseOutcome(
        review_state=state,
        parsed=model_obj.model_dump(mode="json", by_alias=True),
        confidence=model_obj.confidence,
        ambiguities=ambiguities,
        clarifying_questions=questions,
    )


def parse_assignment_brief(raw_text: str) -> ParseOutcome:
    injection_notes = scan_for_injection(raw_text)
    user = wrap_untrusted(raw_text) + (
        "\n\nExtract: title, subject, instructions, due_at (ISO 8601 or null), "
        "ambiguities (list), clarifying_questions (list), confidence (0..1). "
        "If a due date is not explicitly present, set due_at to null and add a "
        "clarifying question."
    )
    try:
        data = get_llm().structured(
            system=SYSTEM_GUARD, user=user,
            schema=ASSIGNMENT_JSON_SCHEMA, schema_name="assignment_brief",
        )
        model_obj = ParsedAssignment.model_validate(data)
    except (ModelError, ValueError) as exc:
        log.warning("assignment_parse_failed", extra={"error": str(exc)})
        return ParseOutcome(
            review_state=ReviewState.FAILED, parsed={}, confidence=0.0,
            ambiguities=[f"Parsing failed: {exc}"], clarifying_questions=[],
        )
    return _finalize(model_obj, injection_notes)


def parse_class_roster(raw_text: str) -> ParseOutcome:
    injection_notes = scan_for_injection(raw_text)
    user = wrap_untrusted(raw_text) + (
        "\n\nExtract a roster: rows[{name, class, guardian_contact}], plus "
        "ambiguities, clarifying_questions, confidence. Flag duplicate names "
        "and missing guardian_contact as ambiguities with clarifying questions."
    )
    try:
        data = get_llm().structured(
            system=SYSTEM_GUARD, user=user,
            schema=ROSTER_JSON_SCHEMA, schema_name="class_roster",
        )
        model_obj = ParsedRoster.model_validate(data)
    except (ModelError, ValueError) as exc:
        log.warning("roster_parse_failed", extra={"error": str(exc)})
        return ParseOutcome(
            review_state=ReviewState.FAILED, parsed={}, confidence=0.0,
            ambiguities=[f"Parsing failed: {exc}"], clarifying_questions=[],
        )
    return _finalize(model_obj, injection_notes)


PARSERS = {
    DocumentType.ASSIGNMENT_BRIEF: parse_assignment_brief,
    DocumentType.CLASS_ROSTER: parse_class_roster,
}


def parse_document(doc_type: DocumentType, raw_text: str) -> ParseOutcome:
    parser = PARSERS.get(doc_type)
    if parser is None:
        # Policy / submission / other: store raw, no structured extraction.
        notes = scan_for_injection(raw_text)
        return ParseOutcome(
            review_state=ReviewState.PARSED if not notes else ReviewState.NEEDS_CLARIFICATION,
            parsed={"raw_text_stored": True}, confidence=1.0,
            ambiguities=notes, clarifying_questions=[],
        )
    return parser(raw_text)
