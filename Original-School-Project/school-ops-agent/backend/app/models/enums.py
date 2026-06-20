"""
Domain enumerations and explicit state-machine transition maps.

The assignment and submission lifecycles are the most safety-critical pieces
of mutable state in the system, so their legal transitions are declared here
as data (not buried in if/else branches). Services validate every transition
against these maps; an illegal transition raises and is audited.
"""
from __future__ import annotations

import enum


class Role(str, enum.Enum):
    ADMIN = "admin"          # School admin / coordinator
    TEACHER = "teacher"
    STUDENT = "student"
    GUARDIAN = "guardian"


class InviteStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"


class DocumentType(str, enum.Enum):
    ASSIGNMENT_BRIEF = "assignment_brief"
    CLASS_ROSTER = "class_roster"
    SCHOOL_POLICY = "school_policy"
    STUDENT_SUBMISSION = "student_submission"
    OTHER = "other"


class ReviewState(str, enum.Enum):
    """Lifecycle of a parsed document awaiting human approval."""
    PENDING_PARSE = "pending_parse"      # uploaded, not yet parsed
    PARSED = "parsed"                    # parsed, awaiting review
    NEEDS_CLARIFICATION = "needs_clarification"  # parser flagged ambiguity
    APPROVED = "approved"                # human accepted parsed output
    REJECTED = "rejected"                # human rejected
    FAILED = "failed"                    # parse/model failure


class AssignmentTargetType(str, enum.Enum):
    CLASS = "class"
    GROUP = "group"
    INDIVIDUAL = "individual"


class AssignmentState(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ACTIVE = "active"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class SubmissionState(str, enum.Enum):
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    REVISION_REQUIRED = "revision_required"
    COMPLETED = "completed"


class StudentProgressState(str, enum.Enum):
    """Per-student status on an assignment, distinct from submission state.

    Drives reminder logic: silent / blocked / submitted students are treated
    differently by the scheduler.
    """
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    SUBMITTED = "submitted"
    COMPLETED = "completed"


# --- Explicit transition maps -------------------------------------------------

ASSIGNMENT_TRANSITIONS: dict[AssignmentState, set[AssignmentState]] = {
    AssignmentState.DRAFT: {AssignmentState.PUBLISHED, AssignmentState.CANCELLED},
    AssignmentState.PUBLISHED: {AssignmentState.ACTIVE, AssignmentState.CANCELLED},
    AssignmentState.ACTIVE: {AssignmentState.ARCHIVED, AssignmentState.CANCELLED},
    AssignmentState.CANCELLED: set(),
    AssignmentState.ARCHIVED: set(),
}

SUBMISSION_TRANSITIONS: dict[SubmissionState, set[SubmissionState]] = {
    SubmissionState.SUBMITTED: {SubmissionState.UNDER_REVIEW},
    SubmissionState.UNDER_REVIEW: {
        SubmissionState.REVISION_REQUIRED,
        SubmissionState.COMPLETED,
    },
    SubmissionState.REVISION_REQUIRED: {SubmissionState.SUBMITTED},  # resubmit
    SubmissionState.COMPLETED: set(),
}


class StateTransitionError(Exception):
    """Raised when an illegal lifecycle transition is attempted."""

    def __init__(self, kind: str, frm, to):
        self.kind = kind
        self.frm = frm
        self.to = to
        super().__init__(f"Illegal {kind} transition: {frm} -> {to}")


def assert_assignment_transition(frm: AssignmentState, to: AssignmentState) -> None:
    if to not in ASSIGNMENT_TRANSITIONS.get(frm, set()):
        raise StateTransitionError("assignment", frm, to)


def assert_submission_transition(frm: SubmissionState, to: SubmissionState) -> None:
    if to not in SUBMISSION_TRANSITIONS.get(frm, set()):
        raise StateTransitionError("submission", frm, to)


class IntentType(str, enum.Enum):
    CREATE_ASSIGNMENT = "create_assignment"
    UPDATE_ASSIGNMENT = "update_assignment"
    CANCEL_ASSIGNMENT = "cancel_assignment"
    PROGRESS_UPDATE = "progress_update"
    BLOCKED_HELP = "blocked_help"
    SUBMISSION = "submission"
    RESUBMISSION = "resubmission"
    TEACHER_FEEDBACK = "teacher_feedback"
    REVISION_REQUEST = "revision_request"
    COMPLETION_DECISION = "completion_decision"
    PARENT_OPT_IN = "parent_opt_in"
    PARENT_DIGEST_REQUEST = "parent_digest_request"
    ESCALATION_ACK = "escalation_acknowledgement"
    ADMIN_CONFIG_CHANGE = "admin_config_change"
    ROSTER_IMPORT = "roster_import"
    POLICY_UPLOAD = "policy_upload"
    UNKNOWN = "unknown"  # also covers unsafe / out-of-scope


class AuditEventType(str, enum.Enum):
    REGISTRATION = "registration"
    LOGIN = "login"
    LOGIN_FAILED = "login_failed"
    INVITE_CREATED = "invite_created"
    INVITE_ACCEPTED = "invite_accepted"
    DOCUMENT_UPLOADED = "document_uploaded"
    DOCUMENT_PARSED = "document_parsed"
    PARSE_APPROVED = "parse_approved"
    PARSE_REJECTED = "parse_rejected"
    ASSIGNMENT_CREATED = "assignment_created"
    ASSIGNMENT_STATE_CHANGED = "assignment_state_changed"
    REMINDER_SENT = "reminder_sent"
    REMINDER_SUPPRESSED = "reminder_suppressed"
    SUBMISSION_RECEIVED = "submission_received"
    SUBMISSION_STATE_CHANGED = "submission_state_changed"
    FEEDBACK_GIVEN = "feedback_given"
    PROGRESS_REPORTED = "progress_reported"
    ACCESS_DENIED = "access_denied"
    MODEL_FAILURE = "model_failure"
    INTENT_CLASSIFIED = "intent_classified"
    CHANNEL_MESSAGE_IN = "channel_message_in"
    CHANNEL_MESSAGE_OUT = "channel_message_out"
