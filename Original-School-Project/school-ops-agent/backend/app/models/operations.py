"""
ORM models for documents, assignments, submissions, reminders, messages,
and the append-only audit log.

These carry the most safety-critical mutable state. Lifecycle columns
(`state`) are always changed through service functions that validate against
the transition maps in ``enums.py`` and emit an audit event.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import GUID, Base
from app.models.core import TimestampMixin
from app.models.enums import (
    AssignmentState,
    AssignmentTargetType,
    AuditEventType,
    DocumentType,
    IntentType,
    ReviewState,
    StudentProgressState,
    SubmissionState,
)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Document(TimestampMixin, Base):
    """An uploaded document plus its parsed, reviewable representation.

    We store: the original bytes location, the parsed structured output, the
    parser's confidence and ambiguity notes, and the human approval state.
    This is exactly what the brief asks for in section 3.2.
    """

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_school", "school_id"),
        Index("ix_documents_review_state", "review_state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    doc_type: Mapped[DocumentType] = mapped_column(String(30), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    storage_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Raw extracted text (post-OCR / post-extraction), kept for re-parsing.
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Parsed structured output as produced by the model, validated against a
    # pydantic schema before storage.
    parsed: Mapped[dict | None] = mapped_column(nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Human-readable list of ambiguities / missing fields the parser flagged.
    ambiguities: Mapped[list | None] = mapped_column(nullable=True)
    # Clarifying questions the system will ask before committing.
    clarifying_questions: Mapped[list | None] = mapped_column(nullable=True)

    review_state: Mapped[ReviewState] = mapped_column(
        String(30), default=ReviewState.PENDING_PARSE, nullable=False
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # SHA-256 of file bytes; used for idempotent re-upload detection.
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Assignment(TimestampMixin, Base):
    __tablename__ = "assignments"
    __table_args__ = (
        Index("ix_assignments_school", "school_id"),
        Index("ix_assignments_class", "class_id"),
        Index("ix_assignments_state", "state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("classes.id", ondelete="CASCADE"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(120), nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    target_type: Mapped[AssignmentTargetType] = mapped_column(
        String(20), default=AssignmentTargetType.CLASS, nullable=False
    )
    state: Mapped[AssignmentState] = mapped_column(
        String(20), default=AssignmentState.DRAFT, nullable=False
    )

    targets: Mapped[list["AssignmentTarget"]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan"
    )
    submissions: Mapped[list["Submission"]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan"
    )


class AssignmentTarget(Base):
    """Which students an assignment applies to.

    For CLASS targets we still materialize one row per enrolled student at
    publish time, so progress tracking and reminders have a concrete row to
    hang state on. This keeps the reminder query simple and auditable.
    """

    __tablename__ = "assignment_targets"
    __table_args__ = (
        UniqueConstraint("assignment_id", "student_id", name="uq_assignment_student"),
        Index("ix_at_assignment", "assignment_id"),
        Index("ix_at_student", "student_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    progress_state: Mapped[StudentProgressState] = mapped_column(
        String(20), default=StudentProgressState.NOT_STARTED, nullable=False
    )
    # Free-text note from the student when blocked / reporting progress.
    progress_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_reminded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reminder_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    assignment: Mapped[Assignment] = relationship(back_populates="targets")
    student: Mapped["object"] = relationship("User")


class Submission(TimestampMixin, Base):
    __tablename__ = "submissions"
    __table_args__ = (
        Index("ix_submissions_assignment", "assignment_id"),
        Index("ix_submissions_student", "student_id"),
        Index("ix_submissions_state", "state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Latest submission supersedes prior ones; attempt increments on resubmit.
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    state: Mapped[SubmissionState] = mapped_column(
        String(20), default=SubmissionState.SUBMITTED, nullable=False
    )
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    assignment: Mapped[Assignment] = relationship(back_populates="submissions")
    feedback: Mapped[list["Feedback"]] = relationship(
        back_populates="submission", cascade="all, delete-orphan"
    )


class Feedback(TimestampMixin, Base):
    __tablename__ = "feedback"
    __table_args__ = (Index("ix_feedback_submission", "submission_id"),)

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Whether this feedback requested a revision or marked completion.
    decision: Mapped[str | None] = mapped_column(String(30), nullable=True)

    submission: Mapped[Submission] = relationship(back_populates="feedback")


class Reminder(TimestampMixin, Base):
    """A scheduled or sent reminder. Persisted so the scheduler is restart-safe
    and so we can audit exactly what was sent and why (or why suppressed)."""

    __tablename__ = "reminders"
    __table_args__ = (
        Index("ix_reminders_school", "school_id"),
        Index("ix_reminders_due", "scheduled_for"),
        UniqueConstraint(
            "assignment_target_id", "dedup_key", name="uq_reminder_dedup"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    assignment_target_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("assignment_targets.id", ondelete="CASCADE"), nullable=False
    )
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    suppression_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Idempotency: one reminder per (target, dedup_key e.g. "overdue:2025-06-13").
    dedup_key: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)


class InboundMessage(TimestampMixin, Base):
    """Canonical envelope for any inbound chat message across channels.

    Storing this lets us (a) dedupe webhook retries via provider_message_id,
    and (b) trace channel -> intent -> action with a correlation id.
    """

    __tablename__ = "inbound_messages"
    __table_args__ = (
        UniqueConstraint("channel", "provider_message_id", name="uq_inbound_provider_msg"),
        Index("ix_inbound_correlation", "correlation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("schools.id", ondelete="CASCADE"), nullable=True
    )
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(120), nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw: Mapped[dict | None] = mapped_column(nullable=True)
    classified_intent: Mapped[IntentType | None] = mapped_column(String(40), nullable=True)
    intent_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)


class IdempotencyKey(TimestampMixin, Base):
    """Stores the result of a previously-processed mutating request keyed by a
    client-supplied (or derived) idempotency key, so retries are no-ops."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("scope", "key", name="uq_idem_scope_key"),)

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    scope: Mapped[str] = mapped_column(String(80), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    # Stored response so a replayed request returns the original result.
    response: Mapped[dict | None] = mapped_column(nullable=True)
    status_code: Mapped[int] = mapped_column(Integer, default=200, nullable=False)


class AuditEvent(Base):
    """Append-only audit log. Every important action writes one row.

    `correlation_id` ties together a whole channel->intent->action->notify
    flow. `actor_user_id` may be null for system/agent actions, in which case
    `actor_label` records 'system' or 'scheduler'.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_school_time", "school_id", "created_at"),
        Index("ix_audit_correlation", "correlation_id"),
        Index("ix_audit_type", "event_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("schools.id", ondelete="CASCADE"), nullable=True
    )
    correlation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    event_type: Mapped[AuditEventType] = mapped_column(String(40), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_label: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # The resource this event concerns, as type + id, for timeline rendering.
    resource_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Human-readable summary + structured detail. Detail is privacy-screened
    # before write (see services/audit.py).
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    detail: Mapped[dict | None] = mapped_column(nullable=True)
