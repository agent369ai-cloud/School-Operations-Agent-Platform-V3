"""
Submission, feedback, and student-progress service.

Handles the full review loop: submit -> under_review -> revision_required ->
resubmit -> ... -> completed, plus the lighter-weight per-student progress
signals (in_progress / blocked) that drive reminders. Every transition is
validated and audited.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.authz import (
    AuthContext,
    require_student_self,
    require_teacher_of_class,
)
from app.models.enums import (
    AuditEventType,
    StudentProgressState,
    SubmissionState,
    assert_submission_transition,
)
from app.models.operations import (
    Assignment,
    AssignmentTarget,
    Feedback,
    Submission,
)
from app.services.audit import record_event


def _target_for(db: Session, assignment_id: uuid.UUID, student_id: uuid.UUID) -> AssignmentTarget | None:
    return (
        db.query(AssignmentTarget)
        .filter(
            AssignmentTarget.assignment_id == assignment_id,
            AssignmentTarget.student_id == student_id,
        )
        .one_or_none()
    )


def report_progress(
    db: Session,
    ctx: AuthContext,
    *,
    assignment: Assignment,
    student_id: uuid.UUID,
    blocked: bool,
    note: str | None = None,
) -> AssignmentTarget:
    require_student_self(
        ctx, resource_school_id=assignment.school_id, student_id=student_id
    )
    target = _target_for(db, assignment.id, student_id)
    if target is None:
        target = AssignmentTarget(
            school_id=assignment.school_id,
            assignment_id=assignment.id,
            student_id=student_id,
        )
        db.add(target)
    target.progress_state = (
        StudentProgressState.BLOCKED if blocked else StudentProgressState.IN_PROGRESS
    )
    target.progress_note = note
    db.flush()
    record_event(
        db,
        event_type=AuditEventType.PROGRESS_REPORTED,
        summary=(
            f"Student reported {'BLOCKED' if blocked else 'progress'} on "
            f"'{assignment.title}'"
        ),
        school_id=assignment.school_id,
        actor_user_id=student_id,
        resource_type="assignment_target",
        resource_id=target.id,
        detail={"blocked": blocked},
    )
    return target


def create_submission(
    db: Session,
    ctx: AuthContext,
    *,
    assignment: Assignment,
    student_id: uuid.UUID,
    body_text: str | None = None,
    document_id: uuid.UUID | None = None,
) -> Submission:
    require_student_self(
        ctx, resource_school_id=assignment.school_id, student_id=student_id
    )
    # Determine attempt number (resubmission increments).
    prior = (
        db.query(Submission)
        .filter(
            Submission.assignment_id == assignment.id,
            Submission.student_id == student_id,
        )
        .order_by(Submission.attempt.desc())
        .first()
    )
    attempt = (prior.attempt + 1) if prior else 1
    submission = Submission(
        school_id=assignment.school_id,
        assignment_id=assignment.id,
        student_id=student_id,
        attempt=attempt,
        state=SubmissionState.SUBMITTED,
        body_text=body_text,
        document_id=document_id,
    )
    db.add(submission)
    # Reflect on the per-student progress row.
    target = _target_for(db, assignment.id, student_id)
    if target:
        target.progress_state = StudentProgressState.SUBMITTED
        db.add(target)
    db.flush()
    record_event(
        db,
        event_type=AuditEventType.SUBMISSION_RECEIVED,
        summary=f"Submission (attempt {attempt}) received for '{assignment.title}'",
        school_id=assignment.school_id,
        actor_user_id=student_id,
        resource_type="submission",
        resource_id=submission.id,
        detail={"attempt": attempt, "has_file": document_id is not None},
    )
    return submission


def transition_submission(
    db: Session, ctx: AuthContext, *, assignment: Assignment, submission: Submission,
    to: SubmissionState,
) -> Submission:
    require_teacher_of_class(
        ctx, resource_school_id=assignment.school_id, class_id=assignment.class_id
    )
    frm = submission.state
    assert_submission_transition(frm, to)
    submission.state = to
    db.add(submission)
    db.flush()
    record_event(
        db,
        event_type=AuditEventType.SUBMISSION_STATE_CHANGED,
        summary=f"Submission {getattr(frm, "value", frm)} -> {getattr(to, "value", to)} for '{assignment.title}'",
        school_id=assignment.school_id,
        actor_user_id=ctx.user_id,
        resource_type="submission",
        resource_id=submission.id,
        detail={"from": getattr(frm, "value", frm), "to": getattr(to, "value", to)},
    )
    return submission


def give_feedback(
    db: Session,
    ctx: AuthContext,
    *,
    assignment: Assignment,
    submission: Submission,
    body: str,
    decision: str | None = None,
) -> Feedback:
    """Teacher feedback. ``decision`` of 'revision' or 'complete' also drives the
    submission state machine and the student's progress row."""
    require_teacher_of_class(
        ctx, resource_school_id=assignment.school_id, class_id=assignment.class_id
    )
    # Move to under_review first if still in submitted.
    if submission.state == SubmissionState.SUBMITTED:
        transition_submission(
            db, ctx, assignment=assignment, submission=submission,
            to=SubmissionState.UNDER_REVIEW,
        )
    feedback = Feedback(
        school_id=assignment.school_id,
        submission_id=submission.id,
        teacher_id=ctx.user_id,
        body=body,
        decision=decision,
    )
    db.add(feedback)
    db.flush()
    record_event(
        db,
        event_type=AuditEventType.FEEDBACK_GIVEN,
        summary=f"Teacher feedback on '{assignment.title}' (decision={decision})",
        school_id=assignment.school_id,
        actor_user_id=ctx.user_id,
        resource_type="submission",
        resource_id=submission.id,
        detail={"decision": decision},
    )
    if decision == "revision":
        transition_submission(
            db, ctx, assignment=assignment, submission=submission,
            to=SubmissionState.REVISION_REQUIRED,
        )
        target = _target_for(db, assignment.id, submission.student_id)
        if target:
            target.progress_state = StudentProgressState.IN_PROGRESS
            db.add(target)
    elif decision == "complete":
        transition_submission(
            db, ctx, assignment=assignment, submission=submission,
            to=SubmissionState.COMPLETED,
        )
        target = _target_for(db, assignment.id, submission.student_id)
        if target:
            target.progress_state = StudentProgressState.COMPLETED
            db.add(target)
    db.flush()
    return feedback
