"""
Class / grade management.

  POST /api/classes                      admin creates a grade/class
  GET  /api/classes                      admin sees all; teacher sees own
  POST /api/classes/{id}/assign-teacher  admin links an existing teacher (M2M)

Demonstrates the teacher<->class many-to-many and school-scoping on every read.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import SchoolClass, User, UserRole, teacher_class_link
from app.auth.deps import get_current_user, require_role
from app.events import audit

router = APIRouter(prefix="/api/classes", tags=["classes"])


class ClassCreate(BaseModel):
    name: str
    grade_level: str | None = None


class ClassOut(BaseModel):
    id: uuid.UUID
    name: str
    grade_level: str | None

    class Config:
        from_attributes = True


class AssignTeacher(BaseModel):
    teacher_id: uuid.UUID


@router.post("", response_model=ClassOut, status_code=status.HTTP_201_CREATED)
def create_class(
    body: ClassCreate,
    user: User = Depends(require_role(UserRole.admin)),
    db: Session = Depends(get_db),
) -> SchoolClass:
    sc = SchoolClass(school_id=user.school_id, name=body.name, grade_level=body.grade_level)
    db.add(sc)
    db.flush()
    audit.record(db, action="class.created", school_id=user.school_id, actor_user_id=user.id,
                 resource_type="class", resource_id=sc.id)
    db.commit()
    return sc


@router.get("", response_model=list[ClassOut])
def list_classes(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SchoolClass]:
    if user.role == UserRole.admin:
        stmt = select(SchoolClass).where(SchoolClass.school_id == user.school_id)
    elif user.role == UserRole.teacher:
        stmt = (
            select(SchoolClass)
            .join(teacher_class_link, teacher_class_link.c.class_id == SchoolClass.id)
            .where(teacher_class_link.c.teacher_id == user.id)
        )
    else:
        return []
    return list(db.execute(stmt).scalars().all())


@router.post("/{class_id}/assign-teacher", status_code=status.HTTP_204_NO_CONTENT)
def assign_teacher(
    class_id: uuid.UUID,
    body: AssignTeacher,
    user: User = Depends(require_role(UserRole.admin)),
    db: Session = Depends(get_db),
) -> None:
    sc = db.get(SchoolClass, class_id)
    if sc is None or sc.school_id != user.school_id:
        raise HTTPException(status_code=404, detail="Class not found")

    teacher = db.get(User, body.teacher_id)
    if teacher is None or teacher.school_id != user.school_id or teacher.role != UserRole.teacher:
        raise HTTPException(status_code=400, detail="Not a teacher in this school")

    # idempotent: linking the same teacher twice is a no-op
    already = db.execute(
        teacher_class_link.select().where(
            teacher_class_link.c.teacher_id == teacher.id,
            teacher_class_link.c.class_id == sc.id,
        )
    ).first()
    if already is None:
        db.execute(teacher_class_link.insert().values(teacher_id=teacher.id, class_id=sc.id))
        audit.record(db, action="class.teacher_assigned", school_id=user.school_id, actor_user_id=user.id,
                     resource_type="class", resource_id=sc.id, payload={"teacher_id": str(teacher.id)})
    db.commit()
