"""
Domain model for the School Operations Agent Platform.

Design intent (what a reviewer / junior should take away):
  * One `users` table holds every actor that authenticates (admin, teacher,
    student, guardian), distinguished by `role`. School-scoping lives on the row.
  * Teacher<->Class is many-to-many; Guardian<->Student is many-to-many.
  * Assignments target a class, a group, or an individual via `assignment_targets`.
  * Documents can attach to school / class / teacher / assignment / student
    (all FKs nullable; exactly which are set depends on doc_type).
  * Assignment and Submission carry explicit status enums = the state machines.
  * audit_events + idempotency_keys make actions traceable and replay-safe.
  * chat_identities links a Telegram/WhatsApp id to a user BEFORE sensitive actions.

Everything is school-scoped: authorization checks join back to `school_id`.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


# --------------------------------------------------------------------------
# Enums (the lifecycles + closed vocabularies)
# --------------------------------------------------------------------------

class UserRole(str, enum.Enum):
    admin = "admin"          # school admin / coordinator
    teacher = "teacher"
    student = "student"
    guardian = "guardian"


class DocType(str, enum.Enum):
    assignment_brief = "assignment_brief"
    roster = "roster"
    policy = "policy"
    submission = "submission"


class ApprovalState(str, enum.Enum):
    pending = "pending"      # parsed, awaiting human review
    approved = "approved"
    rejected = "rejected"


class AssignmentStatus(str, enum.Enum):
    draft = "draft"          # parsed/proposed, not yet approved
    active = "active"
    completed = "completed"
    cancelled = "cancelled"


class SubmissionStatus(str, enum.Enum):
    pending = "pending"
    submitted = "submitted"
    feedback_given = "feedback_given"
    revision_requested = "revision_requested"
    completed = "completed"


class ReminderStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    skipped = "skipped"      # e.g. already submitted, or quiet hours
    escalated = "escalated"  # routed to teacher/guardian
    failed = "failed"


class TargetType(str, enum.Enum):
    klass = "class"
    group = "group"
    individual = "individual"


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)


def _ts() -> Mapped[datetime]:
    return mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())


# --------------------------------------------------------------------------
# Association tables (the many-to-many relationships)
# --------------------------------------------------------------------------

teacher_class_link = sa.Table(
    "teacher_class_link",
    Base.metadata,
    sa.Column("teacher_id", sa.Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("class_id", sa.Uuid, ForeignKey("school_classes.id", ondelete="CASCADE"), primary_key=True),
)

guardian_student_link = sa.Table(
    "guardian_student_link",
    Base.metadata,
    sa.Column("guardian_id", sa.Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("student_id", sa.Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)


# --------------------------------------------------------------------------
# Core entities
# --------------------------------------------------------------------------

class School(Base):
    __tablename__ = "schools"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(sa.String(200))
    # policy knobs (quiet hours etc.) parsed from an uploaded policy doc:
    quiet_hours_start: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)  # 0-23
    quiet_hours_end: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    require_teacher_approval: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    created_at: Mapped[datetime] = _ts()


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("school_id", "email", name="uq_user_school_email"),)

    id: Mapped[uuid.UUID] = _pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), index=True)
    role: Mapped[UserRole] = mapped_column(sa.Enum(UserRole), index=True)
    email: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)  # students may onboard without email
    hashed_password: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(sa.String(200))
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    # a student belongs to one class (nullable for non-students):
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("school_classes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = _ts()

    classes_taught: Mapped[list["SchoolClass"]] = relationship(
        secondary=teacher_class_link, back_populates="teachers"
    )
    guardians: Mapped[list["User"]] = relationship(
        secondary=guardian_student_link,
        primaryjoin=id == guardian_student_link.c.student_id,
        secondaryjoin=id == guardian_student_link.c.guardian_id,
        backref="wards",
    )


class SchoolClass(Base):
    __tablename__ = "school_classes"
    id: Mapped[uuid.UUID] = _pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(sa.String(120))           # e.g. "Grade 5 - B"
    grade_level: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
    created_at: Mapped[datetime] = _ts()

    teachers: Mapped[list[User]] = relationship(
        secondary=teacher_class_link, back_populates="classes_taught"
    )


class Assignment(Base):
    __tablename__ = "assignments"
    id: Mapped[uuid.UUID] = _pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL", use_alter=True, name="fk_assign_src_doc"), nullable=True
    )
    title: Mapped[str] = mapped_column(sa.String(255))
    subject: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    instructions: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    status: Mapped[AssignmentStatus] = mapped_column(
        sa.Enum(AssignmentStatus), default=AssignmentStatus.draft, index=True
    )
    created_at: Mapped[datetime] = _ts()

    targets: Mapped[list["AssignmentTarget"]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan"
    )


class AssignmentTarget(Base):
    """Who an assignment is for: a whole class, a group, or one student."""
    __tablename__ = "assignment_targets"
    id: Mapped[uuid.UUID] = _pk()
    assignment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True)
    target_type: Mapped[TargetType] = mapped_column(sa.Enum(TargetType))
    class_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("school_classes.id", ondelete="CASCADE"), nullable=True)
    student_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    group_label: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)

    assignment: Mapped[Assignment] = relationship(back_populates="targets")


class Document(Base):
    """Original upload + parsed output + ambiguity/approval state."""
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = _pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), index=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    doc_type: Mapped[DocType] = mapped_column(sa.Enum(DocType), index=True)
    original_filename: Mapped[str] = mapped_column(sa.String(255))
    storage_path: Mapped[str] = mapped_column(sa.String(500))
    parsed_json: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    confidence_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    approval_state: Mapped[ApprovalState] = mapped_column(sa.Enum(ApprovalState), default=ApprovalState.pending)
    # optional owners (set per doc_type):
    class_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("school_classes.id", ondelete="SET NULL"), nullable=True)
    teacher_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assignments.id", ondelete="SET NULL"), nullable=True)
    student_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = _ts()


class Submission(Base):
    __tablename__ = "submissions"
    id: Mapped[uuid.UUID] = _pk()
    assignment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    attempt_no: Mapped[int] = mapped_column(sa.Integer, default=1)   # increments on resubmission
    status: Mapped[SubmissionStatus] = mapped_column(
        sa.Enum(SubmissionStatus), default=SubmissionStatus.pending, index=True
    )
    content_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _ts()


class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[uuid.UUID] = _pk()
    submission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    teacher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    body: Mapped[str] = mapped_column(sa.Text)
    decision: Mapped[SubmissionStatus] = mapped_column(sa.Enum(SubmissionStatus))  # revision_requested | completed
    created_at: Mapped[datetime] = _ts()


class Reminder(Base):
    __tablename__ = "reminders"
    id: Mapped[uuid.UUID] = _pk()
    assignment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    scheduled_for: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), index=True)
    status: Mapped[ReminderStatus] = mapped_column(sa.Enum(ReminderStatus), default=ReminderStatus.pending, index=True)
    channel: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)   # telegram / whatsapp
    reason: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)    # why sent/skipped/escalated
    created_at: Mapped[datetime] = _ts()


# --------------------------------------------------------------------------
# Cross-cutting: identity linking, audit, idempotency, invites
# --------------------------------------------------------------------------

class ChatIdentity(Base):
    """A Telegram/WhatsApp identity, linked to a web user before sensitive actions."""
    __tablename__ = "chat_identities"
    __table_args__ = (UniqueConstraint("provider", "external_id", name="uq_chat_provider_external"),)
    id: Mapped[uuid.UUID] = _pk()
    provider: Mapped[str] = mapped_column(sa.String(30))           # "telegram" | "whatsapp"
    external_id: Mapped[str] = mapped_column(sa.String(120))       # chat id / phone
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    school_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("schools.id", ondelete="SET NULL"), nullable=True)
    linked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _ts()


class Invite(Base):
    """Short-lived, single-use, pre-scoped invite for teachers/students/guardians."""
    __tablename__ = "invites"
    id: Mapped[uuid.UUID] = _pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), index=True)
    role: Mapped[UserRole] = mapped_column(sa.Enum(UserRole))
    email: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    token_hash: Mapped[str] = mapped_column(sa.String(255), unique=True, index=True)
    class_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("school_classes.id", ondelete="SET NULL"), nullable=True)
    student_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # guardian->student
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _ts()


class AuditEvent(Base):
    """Append-only timeline. Never updated, never deleted."""
    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = _pk()
    school_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("schools.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # null = system/agent
    action: Mapped[str] = mapped_column(sa.String(80), index=True)       # e.g. "assignment.approved"
    resource_type: Mapped[str | None] = mapped_column(sa.String(60), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(sa.String(64), index=True, nullable=True)
    payload: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)  # keep PII out of here
    created_at: Mapped[datetime] = _ts()


class IdempotencyKey(Base):
    """Dedupe webhooks, double form submits, repeated uploads."""
    __tablename__ = "idempotency_keys"
    id: Mapped[uuid.UUID] = _pk()
    key: Mapped[str] = mapped_column(sa.String(200), unique=True, index=True)
    scope: Mapped[str] = mapped_column(sa.String(60))               # "telegram_update" | "submission" | ...
    result_ref: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)  # id of the thing created
    created_at: Mapped[datetime] = _ts()
