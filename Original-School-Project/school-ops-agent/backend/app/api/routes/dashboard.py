"""Dashboard routes: role-aware aggregated views the frontend renders."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_auth_context
from app.core.authz import AuthContext
from app.db.base import get_db
from app.models.core import Enrollment, SchoolClass, User
from app.models.enums import AssignmentState, Role, StudentProgressState, SubmissionState
from app.models.operations import (
    Assignment,
    AssignmentTarget,
    Document,
    Submission,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/teacher")
def teacher_dashboard(
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    """Live operational view: submissions to review, blocked students, overdue,
    and documents awaiting parse approval — scoped to the teacher's classes."""
    class_ids = list(ctx.class_ids) if ctx.role == Role.TEACHER else None
    aq = db.query(Assignment).filter(Assignment.school_id == ctx.school_id)
    if class_ids is not None:
        aq = aq.filter(Assignment.class_id.in_(class_ids or [None]))
    assignments = aq.all()
    a_ids = [a.id for a in assignments]

    blocked = (
        db.query(AssignmentTarget)
        .filter(
            AssignmentTarget.assignment_id.in_(a_ids or [None]),
            AssignmentTarget.progress_state == StudentProgressState.BLOCKED,
        ).all()
    )
    to_review = (
        db.query(Submission)
        .filter(
            Submission.assignment_id.in_(a_ids or [None]),
            Submission.state.in_([SubmissionState.SUBMITTED,
                                  SubmissionState.UNDER_REVIEW]),
        ).all()
    )
    pending_docs = (
        db.query(Document)
        .filter(Document.school_id == ctx.school_id,
                Document.review_state.in_(["parsed", "needs_clarification"]))
        .all()
    )
    return {
        "assignments": [
            {"id": str(a.id), "title": a.title, "state": getattr(a.state, "value", a.state),
             "due_at": a.due_at.isoformat() if a.due_at else None}
            for a in assignments
        ],
        "blocked_students": [
            {"assignment_id": str(t.assignment_id),
             "student_id": str(t.student_id), "note": t.progress_note}
            for t in blocked
        ],
        "submissions_to_review": [
            {"id": str(s.id), "assignment_id": str(s.assignment_id),
             "student_id": str(s.student_id), "attempt": s.attempt,
             "state": getattr(s.state, "value", s.state)}
            for s in to_review
        ],
        "documents_awaiting_review": [
            {"id": str(d.id), "filename": d.filename,
             "doc_type": getattr(d.doc_type, "value", d.doc_type),
             "review_state": getattr(d.review_state, "value", d.review_state),
             "clarifying_questions": d.clarifying_questions or [],
             "parsed": d.parsed}
            for d in pending_docs
        ],
    }


@router.get("/student")
def student_dashboard(
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    targets = (
        db.query(AssignmentTarget)
        .filter(AssignmentTarget.student_id == ctx.user_id)
        .all()
    )
    out = []
    for t in targets:
        a = db.get(Assignment, t.assignment_id)
        if not a:
            continue
        latest_sub = (
            db.query(Submission)
            .filter(Submission.assignment_id == a.id,
                    Submission.student_id == ctx.user_id)
            .order_by(Submission.attempt.desc()).first()
        )
        out.append({
            "assignment_id": str(a.id), "title": a.title,
            "due_at": a.due_at.isoformat() if a.due_at else None,
            "progress_state": getattr(t.progress_state, "value", t.progress_state),
            "submission_state": getattr(latest_sub.state, "value", latest_sub.state) if latest_sub else None,
            "attempts": latest_sub.attempt if latest_sub else 0,
        })
    return {"assignments": out}


@router.get("/admin")
def admin_dashboard(
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    counts = {
        "classes": db.query(SchoolClass).filter(
            SchoolClass.school_id == ctx.school_id).count(),
        "teachers": db.query(User).filter(
            User.school_id == ctx.school_id, User.role == Role.TEACHER).count(),
        "students": db.query(User).filter(
            User.school_id == ctx.school_id, User.role == Role.STUDENT).count(),
        "guardians": db.query(User).filter(
            User.school_id == ctx.school_id, User.role == Role.GUARDIAN).count(),
        "assignments": db.query(Assignment).filter(
            Assignment.school_id == ctx.school_id).count(),
        "documents_pending": db.query(Document).filter(
            Document.school_id == ctx.school_id,
            Document.review_state.in_(["parsed", "needs_clarification",
                                       "pending_parse"])).count(),
    }
    return {"counts": counts}
