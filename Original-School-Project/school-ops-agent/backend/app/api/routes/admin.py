"""Admin routes: classes, teacher assignment, school policy."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_auth_context, require_roles
from app.core.authz import AuthContext, require_admin
from app.db.base import get_db
from app.models.core import School, SchoolClass, TeacherClassLink, User
from app.models.enums import Role
from app.schemas.api import (
    AssignTeacherRequest,
    ClassResponse,
    CreateClassRequest,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/classes", response_model=ClassResponse, status_code=201)
def create_class(
    body: CreateClassRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    require_admin(ctx)
    sc = SchoolClass(
        school_id=ctx.school_id, name=body.name, grade_level=body.grade_level
    )
    db.add(sc)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A class named '{body.name}' already exists in this school.",
        )
    return ClassResponse(id=sc.id, name=sc.name, grade_level=sc.grade_level)


@router.get("/classes", response_model=list[ClassResponse])
def list_classes(
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    rows = db.query(SchoolClass).filter(SchoolClass.school_id == ctx.school_id).all()
    return [ClassResponse(id=c.id, name=c.name, grade_level=c.grade_level) for c in rows]


@router.delete("/classes/{class_id}", status_code=204)
def delete_class(
    class_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    require_admin(ctx)
    sc = db.get(SchoolClass, class_id)
    if not sc or sc.school_id != ctx.school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")
    try:
        db.delete(sc)
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cannot delete class: it still has enrolled students or active assignments. "
            "Remove them first.",
        )


@router.post("/teacher-assignments", status_code=201)
def assign_teacher(
    body: AssignTeacherRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    require_admin(ctx)
    teacher = db.get(User, body.teacher_id)
    sc = db.get(SchoolClass, body.class_id)
    # Tenancy: both must belong to the admin's school.
    if not teacher or teacher.school_id != ctx.school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "teacher not in your school")
    if not sc or sc.school_id != ctx.school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "class not in your school")
    if teacher.role != Role.TEACHER:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "user is not a teacher")
    exists = db.query(TeacherClassLink).filter(
        TeacherClassLink.teacher_id == teacher.id,
        TeacherClassLink.class_id == sc.id,
    ).one_or_none()
    if exists:
        return {"status": "already_assigned"}
    db.add(TeacherClassLink(
        school_id=ctx.school_id, teacher_id=teacher.id, class_id=sc.id
    ))
    return {"status": "assigned"}


@router.put("/policy")
def set_policy(
    policy: dict,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    require_admin(ctx)
    school = db.get(School, ctx.school_id)
    school.policy = policy
    db.add(school)
    return {"status": "updated", "policy": policy}


@router.get("/policy")
def get_policy(
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    school = db.get(School, ctx.school_id)
    return school.policy or {}


@router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    require_admin(ctx)
    rows = db.query(User).filter(User.school_id == ctx.school_id).all()
    return [
        {"id": str(u.id), "full_name": u.full_name, "role": str(u.role),
         "email": u.email}
        for u in rows
    ]
