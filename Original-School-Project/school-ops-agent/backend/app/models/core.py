"""
ORM models for the School Operations Agent Platform.

Multi-tenancy strategy
----------------------
Every tenant-scoped row carries a ``school_id`` foreign key. This is the
single most important isolation invariant in the system: the authorization
layer always filters by the actor's ``school_id``, and the database enforces
referential integrity so a row cannot reference a resource in another school.

We deliberately denormalize ``school_id`` onto child tables (e.g. submissions
carry both assignment_id and school_id) so that authorization checks never
require a multi-table join to establish tenancy. This trades a little storage
for a much smaller blast radius on the access-control code a junior will edit.

ID strategy
-----------
All primary keys are UUIDs (GUID type) to avoid leaking row counts and to make
IDs safe to expose in URLs and chat.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import GUID, Base
from app.models.enums import (
    AssignmentState,
    AssignmentTargetType,
    AuditEventType,
    DocumentType,
    InviteStatus,
    IntentType,
    ReviewState,
    Role,
    StudentProgressState,
    SubmissionState,
)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )


# ----------------------------------------------------------------------------
# Tenancy root
# ----------------------------------------------------------------------------
class School(TimestampMixin, Base):
    __tablename__ = "schools"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # School-level policy controlling reminders, quiet hours, escalation, etc.
    # Stored as JSON so a junior can extend policy without a migration.
    policy: Mapped[dict] = mapped_column(default=dict, nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="school", cascade="all, delete-orphan")
    classes: Mapped[list["SchoolClass"]] = relationship(back_populates="school", cascade="all, delete-orphan")


# ----------------------------------------------------------------------------
# Users (single table, role-discriminated) + role-specific profiles
# ----------------------------------------------------------------------------
class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("school_id", "email", name="uq_user_school_email"),
        Index("ix_users_school", "school_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[Role] = mapped_column(String(20), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Null for student/guardian accounts that authenticate only via chat link.
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    school: Mapped[School] = relationship(back_populates="users")
    chat_identities: Mapped[list["ChatIdentity"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    # Guardian -> students links (only populated for guardians)
    guardian_links: Mapped[list["GuardianStudentLink"]] = relationship(
        back_populates="guardian",
        foreign_keys="GuardianStudentLink.guardian_id",
        cascade="all, delete-orphan",
    )


class SchoolClass(TimestampMixin, Base):
    """A grade/class within a school (e.g. 'Grade 7-A')."""

    __tablename__ = "classes"
    __table_args__ = (
        UniqueConstraint("school_id", "name", name="uq_class_school_name"),
        Index("ix_classes_school", "school_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    grade_level: Mapped[str | None] = mapped_column(String(50), nullable=True)

    school: Mapped[School] = relationship(back_populates="classes")
    teacher_links: Mapped[list["TeacherClassLink"]] = relationship(
        back_populates="school_class", cascade="all, delete-orphan"
    )
    enrollments: Mapped[list["Enrollment"]] = relationship(
        back_populates="school_class", cascade="all, delete-orphan"
    )


class TeacherClassLink(Base):
    """Many-to-many: teachers <-> classes. A teacher may teach many classes;
    a class may have many teachers."""

    __tablename__ = "teacher_class_links"
    __table_args__ = (
        UniqueConstraint("teacher_id", "class_id", name="uq_teacher_class"),
        Index("ix_tcl_class", "class_id"),
        Index("ix_tcl_teacher", "teacher_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("classes.id", ondelete="CASCADE"), nullable=False
    )

    school_class: Mapped[SchoolClass] = relationship(back_populates="teacher_links")
    teacher: Mapped[User] = relationship()


class Enrollment(Base):
    """A student's membership in a class."""

    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("student_id", "class_id", name="uq_enrollment"),
        Index("ix_enrollment_class", "class_id"),
        Index("ix_enrollment_student", "student_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("classes.id", ondelete="CASCADE"), nullable=False
    )

    school_class: Mapped[SchoolClass] = relationship(back_populates="enrollments")
    student: Mapped[User] = relationship()


class GuardianStudentLink(Base):
    """Links a guardian user to a student they may view (limited detail)."""

    __tablename__ = "guardian_student_links"
    __table_args__ = (
        UniqueConstraint("guardian_id", "student_id", name="uq_guardian_student"),
        Index("ix_gsl_student", "student_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    guardian_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    opted_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    guardian: Mapped[User] = relationship(
        back_populates="guardian_links", foreign_keys=[guardian_id]
    )
    student: Mapped[User] = relationship(foreign_keys=[student_id])


class ChatIdentity(TimestampMixin, Base):
    """Maps an external chat identity (Telegram/WhatsApp) to a platform user.

    Sensitive actions are refused until a chat identity is linked to a real
    account, which is what `verified` gates.
    """

    __tablename__ = "chat_identities"
    __table_args__ = (
        UniqueConstraint("channel", "external_id", name="uq_chat_identity"),
        Index("ix_chat_identity_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # telegram|whatsapp
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped[User] = relationship(back_populates="chat_identities")


class Invite(TimestampMixin, Base):
    """Scoped, short-lived invitation used to onboard teachers/students/guardians.

    The token is stored hashed; the raw token is only ever returned once at
    creation time. Scope columns pin the invite to a specific class/student so
    accepting it cannot cross tenant or class boundaries.
    """

    __tablename__ = "invites"
    __table_args__ = (Index("ix_invite_token_hash", "token_hash"),)

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    role: Mapped[Role] = mapped_column(String(20), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Optional scoping targets:
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("classes.id", ondelete="CASCADE"), nullable=True
    )
    # For guardian invites: the student they will be linked to.
    target_student_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    status: Mapped[InviteStatus] = mapped_column(
        String(20), default=InviteStatus.PENDING, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
