"""Submission/feedback/progress routes, reminders trigger, audit timeline, SSE."""
from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_auth_context, get_current_user
from app.core.authz import AccessDenied, AuthContext, require_admin
from app.db.base import SessionLocal, get_db
from app.models.core import User
from app.models.enums import Role, StateTransitionError, StudentProgressState, SubmissionState
from app.models.operations import Assignment, AssignmentTarget, AuditEvent, Submission
from app.schemas.api import (
    AuditEventResponse,
    CreateSubmissionRequest,
    FeedbackRequest,
    ProgressRequest,
)
from app.scheduler.worker import run_sweep
from app.services import submissions as svc
from app.services.events import Event, bus

router = APIRouter(tags=["operations"])


# --- Submissions ---
@router.post("/submissions", status_code=201)
async def submit(
    body: CreateSubmissionRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    assignment = db.get(Assignment, body.assignment_id)
    if not assignment or assignment.school_id != ctx.school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "assignment not found")
    try:
        sub = svc.create_submission(
            db, ctx, assignment=assignment, student_id=ctx.user_id,
            body_text=body.body_text, document_id=body.document_id,
        )
    except AccessDenied as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.reason)
    await bus.publish(Event(
        type="submission.received", school_id=str(ctx.school_id),
        payload={"assignment_id": str(assignment.id), "attempt": sub.attempt},
    ))
    return {"id": str(sub.id), "attempt": sub.attempt, "state": getattr(sub.state, "value", sub.state)}


@router.post("/progress", status_code=201)
async def progress(
    body: ProgressRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    assignment = db.get(Assignment, body.assignment_id)
    if not assignment or assignment.school_id != ctx.school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "assignment not found")
    try:
        target = svc.report_progress(
            db, ctx, assignment=assignment, student_id=ctx.user_id,
            blocked=body.blocked, note=body.note,
        )
    except AccessDenied as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.reason)
    await bus.publish(Event(
        type="progress.reported", school_id=str(ctx.school_id),
        payload={"assignment_id": str(assignment.id),
                 "blocked": body.blocked,
                 "state": getattr(target.progress_state, "value", target.progress_state)},
    ))
    return {"progress_state": getattr(target.progress_state, "value", target.progress_state)}


@router.post("/teacher/unblock", status_code=200)
async def teacher_unblock(
    body: dict,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    """Teacher follows up on a blocked student: adds a note and clears the block."""
    if ctx.role not in (Role.TEACHER, Role.ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "teacher or admin only")
    assignment_id = body.get("assignment_id")
    student_id = body.get("student_id")
    note = body.get("note", "")
    if not assignment_id or not student_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "assignment_id and student_id required")
    target = (
        db.query(AssignmentTarget)
        .filter(
            AssignmentTarget.assignment_id == uuid.UUID(assignment_id),
            AssignmentTarget.student_id == uuid.UUID(student_id),
        )
        .one_or_none()
    )
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no progress record for that student/assignment")
    target.teacher_note = note
    target.progress_state = StudentProgressState.IN_PROGRESS
    db.add(target)
    db.commit()
    await bus.publish(Event(
        type="progress.reported", school_id=str(ctx.school_id),
        payload={"assignment_id": assignment_id, "blocked": False,
                 "state": StudentProgressState.IN_PROGRESS.value},
    ))
    return {"status": "unblocked", "teacher_note": note}


@router.post("/submissions/{submission_id}/ai-review", status_code=200)
def generate_ai_review(
    submission_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    """Run (or re-run) AI review on an existing submission. Teacher only."""
    if ctx.role not in (Role.TEACHER, Role.ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "teachers only")
    sub = db.get(Submission, submission_id)
    if not sub or sub.school_id != ctx.school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "submission not found")
    assignment = db.get(Assignment, sub.assignment_id)
    if not assignment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "assignment not found")
    result = svc._run_ai_review(assignment, sub.body_text)
    if result is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "no submission text to review")
    sub.ai_review = result
    db.add(sub)
    db.commit()
    return result


@router.post("/feedback", status_code=201)
async def feedback(
    body: FeedbackRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    submission = db.get(Submission, body.submission_id)
    if not submission or submission.school_id != ctx.school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "submission not found")
    assignment = db.get(Assignment, submission.assignment_id)
    try:
        fb = svc.give_feedback(
            db, ctx, assignment=assignment, submission=submission,
            body=body.body, decision=body.decision,
        )
    except AccessDenied as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.reason)
    except StateTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    await bus.publish(Event(
        type="feedback.given", school_id=str(ctx.school_id),
        payload={"submission_id": str(submission.id),
                 "decision": body.decision,
                 "submission_state": getattr(submission.state, "value", submission.state)},
    ))
    return {"id": str(fb.id), "submission_state": getattr(submission.state, "value", submission.state)}


# --- Reminders (manual trigger for demo) ---
@router.post("/reminders/run")
def run_reminders(
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    require_admin(ctx)  # only staff fire the sweep manually
    summary = run_sweep(db, manual=True)
    return summary


# --- Audit timeline ---
@router.get("/audit", response_model=list[AuditEventResponse])
def audit_timeline(
    correlation_id: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    # Tenancy: never expose another school's events.
    q = db.query(AuditEvent).filter(AuditEvent.school_id == ctx.school_id)
    if correlation_id:
        q = q.filter(AuditEvent.correlation_id == correlation_id)
    rows = q.order_by(AuditEvent.created_at.desc()).limit(min(limit, 500)).all()
    return [
        AuditEventResponse(
            id=e.id, created_at=e.created_at, event_type=e.event_type.value
            if hasattr(e.event_type, "value") else str(e.event_type),
            summary=e.summary, actor_label=e.actor_label,
            correlation_id=e.correlation_id, resource_type=e.resource_type,
            resource_id=e.resource_id, detail=e.detail,
        )
        for e in rows
    ]


# --- Live updates (SSE) ---
@router.get("/events/stream")
async def events_stream(
    request: Request,
    user: User = Depends(get_current_user),
):
    """Server-Sent Events stream scoped to the caller's school."""
    school_id = str(user.school_id)
    queue = await bus.subscribe(school_id)

    async def event_gen():
        try:
            # Initial comment to open the stream promptly.
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield event.to_sse()
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"  # heartbeat
        finally:
            await bus.unsubscribe(school_id, queue)

    return StreamingResponse(event_gen(), media_type="text/event-stream")
