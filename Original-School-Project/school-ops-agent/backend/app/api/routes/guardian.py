"""Guardian routes: view linked students and manage opt-in."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_auth_context, get_current_user
from app.core.authz import AuthContext
from app.db.base import get_db
from app.models.core import GuardianStudentLink, User
from app.models.enums import Role

router = APIRouter(prefix="/guardian", tags=["guardian"])


@router.get("/students")
def list_my_students(
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
    user: User = Depends(get_current_user),
):
    if user.role != Role.GUARDIAN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "guardian only")
    links = (
        db.query(GuardianStudentLink)
        .filter(GuardianStudentLink.guardian_id == ctx.user_id)
        .all()
    )
    result = []
    for link in links:
        student = db.get(User, link.student_id)
        if student:
            result.append({
                "student_id": str(student.id),
                "student_name": student.full_name,
                "opted_in": link.opted_in,
            })
    return result


@router.post("/students/{student_id}/opt-in")
def set_opt_in(
    student_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
    user: User = Depends(get_current_user),
):
    if user.role != Role.GUARDIAN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "guardian only")
    link = (
        db.query(GuardianStudentLink)
        .filter(
            GuardianStudentLink.guardian_id == ctx.user_id,
            GuardianStudentLink.student_id == student_id,
        )
        .one_or_none()
    )
    if not link:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no link to that student")
    link.opted_in = not link.opted_in
    db.add(link)
    db.commit()
    return {"student_id": str(student_id), "opted_in": link.opted_in}
