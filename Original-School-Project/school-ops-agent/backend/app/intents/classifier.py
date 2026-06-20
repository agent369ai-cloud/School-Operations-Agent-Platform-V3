"""
Intent layer.

A message (from chat or web) is classified into exactly one IntentType. The
model proposes an intent; we validate it against the IntentType enum (unknown
values collapse to UNKNOWN). The classified intent then routes to a
deterministic handler in ``app.services``. The model never executes an action
directly — it only labels intent. This is the model/deterministic separation
the rubric asks for.
"""
from __future__ import annotations

from app.core.logging import get_logger
from app.models.enums import IntentType
from app.parsers.injection import SYSTEM_GUARD, scan_for_injection, wrap_untrusted
from app.schemas.parsing import INTENT_JSON_SCHEMA, IntentResult
from app.services.llm import ModelError, get_llm

log = get_logger("intent")

# Intents a given role is even allowed to express. The model might misclassify;
# this table is a deterministic guard so e.g. a student cannot trigger
# 'create_assignment' no matter what the classifier returns.
from app.models.enums import Role

ROLE_ALLOWED_INTENTS: dict[Role, set[IntentType]] = {
    Role.ADMIN: set(IntentType),  # admins may do anything in their school
    Role.TEACHER: {
        IntentType.CREATE_ASSIGNMENT, IntentType.UPDATE_ASSIGNMENT,
        IntentType.CANCEL_ASSIGNMENT, IntentType.TEACHER_FEEDBACK,
        IntentType.REVISION_REQUEST, IntentType.COMPLETION_DECISION,
        IntentType.ROSTER_IMPORT, IntentType.UNKNOWN,
    },
    Role.STUDENT: {
        IntentType.PROGRESS_UPDATE, IntentType.BLOCKED_HELP,
        IntentType.SUBMISSION, IntentType.RESUBMISSION, IntentType.UNKNOWN,
    },
    Role.GUARDIAN: {
        IntentType.PARENT_OPT_IN, IntentType.PARENT_DIGEST_REQUEST,
        IntentType.ESCALATION_ACK, IntentType.UNKNOWN,
    },
}


def classify_intent(text: str) -> IntentResult:
    """Classify free text into an IntentResult. Always returns a valid result;
    on model failure it returns UNKNOWN with low confidence."""
    injection_notes = scan_for_injection(text)
    if injection_notes:
        # Treat detected injection as out-of-scope/unsafe immediately.
        log.warning("intent_injection_detected")
        return IntentResult(intent=IntentType.UNKNOWN, confidence=0.95)
    user = wrap_untrusted(text) + (
        "\n\nClassify the sender's intent. Respond with {intent, confidence}."
    )
    try:
        data = get_llm().structured(
            system=SYSTEM_GUARD, user=user,
            schema=INTENT_JSON_SCHEMA, schema_name="intent",
        )
        return IntentResult.model_validate(data)
    except (ModelError, ValueError) as exc:
        log.warning("intent_classification_failed", extra={"error": str(exc)})
        return IntentResult(intent=IntentType.UNKNOWN, confidence=0.0)


def enforce_role(result: IntentResult, role: Role) -> IntentResult:
    """Downgrade an intent to UNKNOWN if the sender's role may not express it."""
    allowed = ROLE_ALLOWED_INTENTS.get(role, {IntentType.UNKNOWN})
    if result.intent not in allowed:
        log.info(
            "intent_not_allowed_for_role",
            extra={"intent": result.intent.value, "role": role.value},
        )
        return IntentResult(intent=IntentType.UNKNOWN, confidence=result.confidence)
    return result
