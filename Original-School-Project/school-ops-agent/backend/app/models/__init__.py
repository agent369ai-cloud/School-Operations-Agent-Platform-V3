"""Aggregate import so ``Base.metadata`` sees every table."""
from app.models.core import (  # noqa: F401
    ChatIdentity,
    Enrollment,
    GuardianStudentLink,
    Invite,
    School,
    SchoolClass,
    TeacherClassLink,
    User,
)
from app.models.enums import (  # noqa: F401
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
from app.models.operations import (  # noqa: F401
    Assignment,
    AssignmentTarget,
    AuditEvent,
    Document,
    Feedback,
    IdempotencyKey,
    InboundMessage,
    Reminder,
    Submission,
)

__all__ = [
    "School",
    "User",
    "SchoolClass",
    "TeacherClassLink",
    "Enrollment",
    "GuardianStudentLink",
    "ChatIdentity",
    "Invite",
    "Document",
    "Assignment",
    "AssignmentTarget",
    "Submission",
    "Feedback",
    "Reminder",
    "InboundMessage",
    "IdempotencyKey",
    "AuditEvent",
]
