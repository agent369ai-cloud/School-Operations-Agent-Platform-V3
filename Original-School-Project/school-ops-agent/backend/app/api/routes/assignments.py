"""Assignment routes: create, publish/activate, list (role-scoped)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_auth_context
from app.core.authz import AccessDenied, AuthContext
from app.db.base import get_db
from app.models.enums import (
    AssignmentState,
    AssignmentTargetType,
    Role,
    StateTransitionError,
)
from app.models.operations import Assignment, AssignmentTarget
from app.schemas.api import (
    AssignmentResponse,
    CreateAssignmentRequest,
    TransitionRequest,
)
from app.services import assignments as svc
from app.services import idempotency as idem
from app.services.events import Event, bus

router = APIRouter(prefix="/assignments", tags=["assignments"])


def _to_response(a: Assignment) -> AssignmentResponse:
    return AssignmentResponse(
        id=a.id, title=a.title, subject=a.subject, instructions=a.instructions,
        due_at=a.due_at, state=a.state, class_id=a.class_id,
    )


@router.post("", response_model=AssignmentResponse, status_code=201)
async def create_assignment(
    body: CreateAssignmentRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
    idempotency_key: str | None = Header(default=None),
):
    # Idempotent create: a double form-submit with the same key is a no-op.
    if idempotency_key:
        claim = idem.begin(db, scope=f"create_assignment:{ctx.school_id}",
                           key=idempotency_key)
        if claim.is_replay and claim.record.response:
            return AssignmentResponse(**claim.record.response)
    assignment = svc.create_assignment(
        db, ctx, title=body.title, class_id=body.class_id, subject=body.subject,
        instructions=body.instructions, due_at=body.due_at,
        target_type=body.target_type,
    )
    resp = _to_response(assignment)
    if idempotency_key:
        idem.complete(db, claim.record, response=resp.model_dump(mode="json"),
                      status_code=201)
    await bus.publish(Event(
        type="assignment.created", school_id=str(ctx.school_id),
        payload={"id": str(assignment.id), "title": assignment.title},
    ))
    return resp


@router.post("/{assignment_id}/transition", response_model=AssignmentResponse)
async def transition(
    assignment_id: uuid.UUID,
    body: TransitionRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    assignment = db.get(Assignment, assignment_id)
    if not assignment or assignment.school_id != ctx.school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "assignment not found")
    try:
        to = AssignmentState(body.to)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown target state")
    try:
        svc.transition_assignment(db, ctx, assignment, to)
    except StateTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    await bus.publish(Event(
        type="assignment.state_changed", school_id=str(ctx.school_id),
        payload={"id": str(assignment.id), "state": str(assignment.state)},
    ))
    return _to_response(assignment)


@router.get("", response_model=list[AssignmentResponse])
def list_assignments(
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    q = db.query(Assignment).filter(Assignment.school_id == ctx.school_id)
    if ctx.role == Role.TEACHER:
        q = q.filter(Assignment.class_id.in_(ctx.class_ids or [None]))
    elif ctx.role == Role.STUDENT:
        # Only assignments the student is targeted by.
        target_assignment_ids = {
            t.assignment_id for t in db.query(AssignmentTarget).filter(
                AssignmentTarget.student_id == ctx.user_id
            )
        }
        q = q.filter(Assignment.id.in_(target_assignment_ids or [None]))
    elif ctx.role == Role.GUARDIAN:
        # Guardians see only assignments targeting their linked students.
        target_assignment_ids = {
            t.assignment_id for t in db.query(AssignmentTarget).filter(
                AssignmentTarget.student_id.in_(ctx.student_ids or [None])
            )
        }
        q = q.filter(Assignment.id.in_(target_assignment_ids or [None]))
    return [_to_response(a) for a in q.all()]
