"""
Channel dispatcher: the chat-side orchestrator.

Flow (each step audited under one correlation id):
  inbound webhook -> canonical envelope -> idempotent store ->
  resolve chat identity -> classify intent (model) -> role-enforce intent ->
  deterministic handler -> reply.

Sensitive actions require a *verified* linked identity; an unlinked chat user
is guided to link first. Unknown/unsafe intents get a safe fallback reply and
never mutate state.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.authz import AuthContext
from app.core.logging import get_logger, new_correlation_id, set_correlation_id
from app.channels.adapter import CanonicalMessage, get_adapter
from app.intents.classifier import classify_intent, enforce_role
from app.models.core import ChatIdentity, Enrollment, GuardianStudentLink, TeacherClassLink, User
from app.models.enums import (
    AuditEventType,
    AssignmentState,
    IntentType,
    Role,
    StudentProgressState,
)
from app.models.operations import Assignment, AssignmentTarget, InboundMessage
from app.services.audit import record_event
from app.services import submissions as submission_svc

log = get_logger("dispatch")


def _build_ctx(db: Session, user: User) -> AuthContext:
    class_ids: set = set()
    student_ids: set = set()
    if user.role == Role.TEACHER:
        class_ids = {
            l.class_id for l in db.query(TeacherClassLink).filter(
                TeacherClassLink.teacher_id == user.id
            )
        }
    elif user.role == Role.STUDENT:
        class_ids = {
            e.class_id for e in db.query(Enrollment).filter(
                Enrollment.student_id == user.id
            )
        }
    elif user.role == Role.GUARDIAN:
        student_ids = {
            g.student_id for g in db.query(GuardianStudentLink).filter(
                GuardianStudentLink.guardian_id == user.id,
                GuardianStudentLink.opted_in.is_(True),
            )
        }
    return AuthContext(
        user_id=user.id, school_id=user.school_id, role=user.role,
        class_ids=frozenset(class_ids), student_ids=frozenset(student_ids),
    )


def _latest_open_assignment(db: Session, student_id: uuid_type) -> Assignment | None:  # type: ignore
    target = (
        db.query(AssignmentTarget)
        .join(Assignment, Assignment.id == AssignmentTarget.assignment_id)
        .filter(
            AssignmentTarget.student_id == student_id,
            Assignment.state == AssignmentState.ACTIVE,
            AssignmentTarget.progress_state.notin_(
                [StudentProgressState.COMPLETED]
            ),
        )
        .order_by(Assignment.due_at.is_(None), Assignment.due_at.asc())
        .first()
    )
    return db.get(Assignment, target.assignment_id) if target else None


import uuid as uuid_type  # noqa: E402  (used in annotation above)


def handle_inbound(db: Session, msg: CanonicalMessage) -> str:
    """Process one inbound message; returns the reply text (also sent via the
    adapter). Idempotent on (channel, provider_message_id)."""
    cid = set_correlation_id(new_correlation_id())

    # Idempotent envelope store. Unique constraint dedupes provider retries.
    from sqlalchemy.exc import IntegrityError

    inbound = InboundMessage(
        correlation_id=cid, channel=msg.channel,
        external_user_id=msg.external_user_id,
        provider_message_id=msg.provider_message_id,
        text=msg.text, raw=msg.raw,
    )
    db.add(inbound)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        log.info("duplicate_inbound_ignored",
                 extra={"provider_message_id": msg.provider_message_id})
        return ""  # already processed

    record_event(
        db, event_type=AuditEventType.CHANNEL_MESSAGE_IN,
        summary=f"Inbound {msg.channel} message",
        resource_type="inbound_message", resource_id=inbound.id,
        detail={"channel": msg.channel}, correlation_id=cid,
    )

    # Resolve linked identity.
    identity = (
        db.query(ChatIdentity)
        .filter(ChatIdentity.channel == msg.channel,
                ChatIdentity.external_id == msg.external_user_id)
        .one_or_none()
    )
    if identity is None or not identity.verified:
        reply = ("Your chat is not linked to a school account yet. Please open "
                 "the link from your invite to connect before sending requests.")
        _reply(db, msg, reply, cid)
        return reply

    user = db.get(User, identity.user_id)
    inbound.school_id = user.school_id
    db.add(inbound)
    ctx = _build_ctx(db, user)

    # Classify + role-enforce.
    result = enforce_role(classify_intent(msg.text or ""), user.role)
    inbound.classified_intent = result.intent
    inbound.intent_confidence = result.confidence
    db.add(inbound)
    record_event(
        db, event_type=AuditEventType.INTENT_CLASSIFIED,
        summary=f"Intent: {result.intent.value} ({result.confidence:.2f})",
        school_id=user.school_id, actor_user_id=user.id,
        resource_type="inbound_message", resource_id=inbound.id,
        detail={"intent": result.intent.value, "confidence": result.confidence},
        correlation_id=cid,
    )

    reply = _route(db, ctx, user, result.intent, msg.text or "")
    _reply(db, msg, reply, cid)
    db.commit()
    return reply


def _route(db: Session, ctx: AuthContext, user: User, intent: IntentType, text: str) -> str:
    if intent in (IntentType.BLOCKED_HELP, IntentType.PROGRESS_UPDATE):
        assignment = _latest_open_assignment(db, user.id)
        if not assignment:
            return "You have no open assignments right now."
        blocked = intent == IntentType.BLOCKED_HELP
        submission_svc.report_progress(
            db, ctx, assignment=assignment, student_id=user.id,
            blocked=blocked, note=text[:500],
        )
        return (
            f"Got it — I've marked '{assignment.title}' as "
            f"{'blocked and notified your teacher' if blocked else 'in progress'}."
        )

    if intent in (IntentType.SUBMISSION, IntentType.RESUBMISSION):
        assignment = _latest_open_assignment(db, user.id)
        if not assignment:
            return "You have no open assignments to submit to right now."
        submission_svc.create_submission(
            db, ctx, assignment=assignment, student_id=user.id, body_text=text[:2000],
        )
        return f"Your submission for '{assignment.title}' was received. Thank you!"

    if intent == IntentType.PARENT_OPT_IN:
        links = db.query(GuardianStudentLink).filter(
            GuardianStudentLink.guardian_id == user.id
        ).all()
        for l in links:
            l.opted_in = True
            db.add(l)
        return "You're opted in to progress updates for your linked child(ren)."

    if intent == IntentType.PARENT_DIGEST_REQUEST:
        links = db.query(GuardianStudentLink).filter(
            GuardianStudentLink.guardian_id == user.id,
            GuardianStudentLink.opted_in.is_(True),
        ).all()
        if not links:
            return ("You're not linked to any students yet, or haven't opted in. "
                    "Reply 'opt in' to start receiving updates.")
        lines = []
        for link in links:
            student = db.get(User, link.student_id)
            if not student:
                continue
            targets = (
                db.query(AssignmentTarget)
                .join(Assignment, Assignment.id == AssignmentTarget.assignment_id)
                .filter(
                    AssignmentTarget.student_id == student.id,
                    Assignment.state == AssignmentState.ACTIVE,
                )
                .all()
            )
            if not targets:
                lines.append(f"{student.full_name}: no active assignments.")
            else:
                for t in targets:
                    a = db.get(Assignment, t.assignment_id)
                    if a:
                        lines.append(
                            f"{student.full_name} — '{a.title}': "
                            f"{getattr(t.progress_state, 'value', t.progress_state)}"
                        )
        return "Progress digest:\n" + "\n".join(lines) if lines else "No data available."

    if intent == IntentType.UNKNOWN:
        return ("Sorry, I couldn't safely interpret that. A teacher or admin can "
                "help — try rephrasing, or use the web app for this action.")

    # Teacher/admin chat intents are acknowledged but routed to the web app for
    # high-impact confirmation (create/cancel assignment, feedback).
    return ("That action needs confirmation in the web app. I've noted your "
            "request; please review and approve it there.")


def _reply(db: Session, msg: CanonicalMessage, text: str, cid: str) -> None:
    if not text:
        return
    get_adapter(msg.channel).send(external_user_id=msg.external_user_id, text=text)
    record_event(
        db, event_type=AuditEventType.CHANNEL_MESSAGE_OUT,
        summary=f"Reply sent on {msg.channel}",
        resource_type="channel", resource_id=msg.external_user_id,
        correlation_id=cid,
    )
