"""
Assignment service.

All assignment lifecycle changes go through here so that (a) every transition
is validated against the state machine, and (b) every change emits an audit
event. Publishing an assignment materializes one AssignmentTarget per enrolled
student, which is what reminders and progress tracking hang off.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.authz import AuthContext, require_teacher_of_class
from app.models.enums import (
    AssignmentState,
    AssignmentTargetType,
    AuditEventType,
    StudentProgressState,
    assert_assignment_transition,
)
from app.models.core import Enrollment
from app.models.operations import Assignment, AssignmentTarget
from app.services.audit import record_event


def create_assignment(
    db: Session,
    ctx: AuthContext,
    *,
    title: str,
    class_id: uuid.UUID | None,
    subject: str | None = None,
    instructions: str | None = None,
    due_at: datetime | None = None,
    target_type: AssignmentTargetType = AssignmentTargetType.CLASS,
    source_document_id: uuid.UUID | None = None,
) -> Assignment:
    require_teacher_of_class(ctx, resource_school_id=ctx.school_id, class_id=class_id)
    assignment = Assignment(
        school_id=ctx.school_id,
        class_id=class_id,
        created_by=ctx.user_id,
        title=title,
        subject=subject,
        instructions=instructions,
        due_at=due_at,
        target_type=target_type,
        state=AssignmentState.DRAFT,
        source_document_id=source_document_id,
    )
    db.add(assignment)
    db.flush()
    record_event(
        db,
        event_type=AuditEventType.ASSIGNMENT_CREATED,
        summary=f"Assignment '{title}' created as draft",
        school_id=ctx.school_id,
        actor_user_id=ctx.user_id,
        resource_type="assignment",
        resource_id=assignment.id,
        detail={"class_id": str(class_id) if class_id else None,
                "target_type": getattr(target_type, "value", target_type)},
    )
    return assignment


def transition_assignment(
    db: Session, ctx: AuthContext, assignment: Assignment, to: AssignmentState
) -> Assignment:
    require_teacher_of_class(
        ctx, resource_school_id=assignment.school_id, class_id=assignment.class_id
    )
    frm = assignment.state
    assert_assignment_transition(frm, to)  # raises StateTransitionError if illegal
    assignment.state = to
    db.add(assignment)
    # On publish, materialize targets for every enrolled student.
    if to == AssignmentState.PUBLISHED and assignment.class_id:
        _materialize_targets(db, assignment)
    db.flush()
    record_event(
        db,
        event_type=AuditEventType.ASSIGNMENT_STATE_CHANGED,
        summary=f"Assignment '{assignment.title}' {getattr(frm, "value", frm)} -> {getattr(to, "value", to)}",
        school_id=assignment.school_id,
        actor_user_id=ctx.user_id,
        resource_type="assignment",
        resource_id=assignment.id,
        detail={"from": getattr(frm, "value", frm), "to": getattr(to, "value", to)},
    )
    return assignment


def _materialize_targets(db: Session, assignment: Assignment) -> None:
    existing = {
        t.student_id
        for t in db.query(AssignmentTarget).filter(
            AssignmentTarget.assignment_id == assignment.id
        )
    }
    enrollments = db.query(Enrollment).filter(
        Enrollment.class_id == assignment.class_id,
        Enrollment.school_id == assignment.school_id,
    )
    for enr in enrollments:
        if enr.student_id in existing:
            continue
        db.add(
            AssignmentTarget(
                school_id=assignment.school_id,
                assignment_id=assignment.id,
                student_id=enr.student_id,
                progress_state=StudentProgressState.NOT_STARTED,
            )
        )


def add_individual_target(
    db: Session, ctx: AuthContext, assignment: Assignment, student_id: uuid.UUID
) -> AssignmentTarget:
    require_teacher_of_class(
        ctx, resource_school_id=assignment.school_id, class_id=assignment.class_id
    )
    target = AssignmentTarget(
        school_id=assignment.school_id,
        assignment_id=assignment.id,
        student_id=student_id,
        progress_state=StudentProgressState.NOT_STARTED,
    )
    db.add(target)
    db.flush()
    return target
