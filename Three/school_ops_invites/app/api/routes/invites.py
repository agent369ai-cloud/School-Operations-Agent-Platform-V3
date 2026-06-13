"""
Invite + onboarding flow.

  POST /api/invites         admin/teacher issues a scoped, single-use invite
  POST /api/invites/accept  invitee sets a password and is linked correctly

Scoping rules enforced server-side (this is the "no cross-school/cross-class
onboarding mistakes" requirement):
  * teacher invite  -> optional class_id; on accept, teacher is linked to it
  * student invite  -> class_id REQUIRED and must belong to the inviter's school
  * guardian invite -> student_id REQUIRED, student must be in the inviter's school
  * a TEACHER inviter may only invite into classes they actually teach
Admins cannot be invited (a school's first admin is created at registration).

Delivery for the demo: the raw token is returned in the response (shown once)
and the accept_url is built for convenience. Swap to email/Telegram in prod by
sending `raw` instead of returning it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import (
    Invite,
    SchoolClass,
    User,
    UserRole,
    teacher_class_link,
    guardian_student_link,
)
from app.auth.deps import require_role
from app.auth.security import create_access_token, create_refresh_token, hash_password
from app.auth.invites import default_expiry, generate_invite_token, hash_token
from app.events import audit

router = APIRouter(prefix="/api/invites", tags=["invites"])


# --- schemas ---

class InviteCreate(BaseModel):
    role: UserRole
    email: EmailStr | None = None
    class_id: uuid.UUID | None = None     # teacher assignment / student enrollment
    student_id: uuid.UUID | None = None   # guardian -> student link
    expires_hours: int = 72


class InviteOut(BaseModel):
    invite_token: str        # raw token -- shown ONCE
    accept_url: str
    role: UserRole
    expires_at: datetime


class InviteAccept(BaseModel):
    token: str
    full_name: str
    email: EmailStr
    password: str


# --- create ---

@router.post("", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
def create_invite(
    body: InviteCreate,
    actor: User = Depends(require_role(UserRole.admin, UserRole.teacher)),
    db: Session = Depends(get_db),
) -> InviteOut:
    if body.role == UserRole.admin:
        raise HTTPException(400, "Cannot invite an admin")

    # role-specific required scoping
    if body.role == UserRole.student:
        if body.class_id is None:
            raise HTTPException(400, "class_id is required for a student invite")
        sc = db.get(SchoolClass, body.class_id)
        if sc is None or sc.school_id != actor.school_id:
            raise HTTPException(400, "class_id is not in your school")

    if body.role == UserRole.guardian:
        if body.student_id is None:
            raise HTTPException(400, "student_id is required for a guardian invite")
        student = db.get(User, body.student_id)
        if student is None or student.school_id != actor.school_id or student.role != UserRole.student:
            raise HTTPException(400, "student_id is not a student in your school")

    # teachers have a narrower reach than admins
    if actor.role == UserRole.teacher:
        if body.role not in (UserRole.student, UserRole.guardian):
            raise HTTPException(403, "Teachers can only invite students or guardians")
        if body.role == UserRole.student:
            teaches = db.execute(
                teacher_class_link.select().where(
                    teacher_class_link.c.teacher_id == actor.id,
                    teacher_class_link.c.class_id == body.class_id,
                )
            ).first()
            if teaches is None:
                raise HTTPException(403, "You don't teach that class")
        if body.role == UserRole.guardian:
            student = db.get(User, body.student_id)
            ok = student.class_id is not None and db.execute(
                teacher_class_link.select().where(
                    teacher_class_link.c.teacher_id == actor.id,
                    teacher_class_link.c.class_id == student.class_id,
                )
            ).first() is not None
            if not ok:
                raise HTTPException(403, "That student isn't in a class you teach")

    raw, token_hash = generate_invite_token()
    inv = Invite(
        school_id=actor.school_id,
        role=body.role,
        email=str(body.email) if body.email else None,
        token_hash=token_hash,
        class_id=body.class_id,
        student_id=body.student_id,
        expires_at=default_expiry(body.expires_hours),
    )
    db.add(inv)
    db.flush()
    audit.record(db, action="invite.created", school_id=actor.school_id, actor_user_id=actor.id,
                 resource_type="invite", resource_id=inv.id, payload={"role": body.role.value})
    db.commit()

    base = settings.PUBLIC_BASE_URL or "http://localhost:8000"
    return InviteOut(
        invite_token=raw,
        accept_url=f"{base}/api/invites/accept?token={raw}",
        role=body.role,
        expires_at=inv.expires_at,
    )


# --- accept (public; the token IS the authorization) ---

@router.post("/accept")
def accept_invite(body: InviteAccept, db: Session = Depends(get_db)) -> dict:
    inv = db.execute(
        select(Invite).where(Invite.token_hash == hash_token(body.token))
    ).scalars().first()

    if inv is None:
        raise HTTPException(400, "Invalid invite token")
    if inv.used_at is not None:
        raise HTTPException(400, "Invite has already been used")
    if inv.expires_at < datetime.now(timezone.utc):
        raise HTTPException(400, "Invite has expired")

    # email unique within the school
    dupe = db.execute(
        select(User).where(User.school_id == inv.school_id, User.email == str(body.email))
    ).scalars().first()
    if dupe is not None:
        raise HTTPException(409, "Email already registered in this school")

    user = User(
        school_id=inv.school_id,
        role=inv.role,
        email=str(body.email),
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        class_id=inv.class_id if inv.role == UserRole.student else None,
    )
    db.add(user)
    db.flush()

    if inv.role == UserRole.teacher and inv.class_id is not None:
        db.execute(teacher_class_link.insert().values(teacher_id=user.id, class_id=inv.class_id))
    if inv.role == UserRole.guardian and inv.student_id is not None:
        db.execute(guardian_student_link.insert().values(guardian_id=user.id, student_id=inv.student_id))

    inv.used_at = datetime.now(timezone.utc)
    audit.record(db, action="invite.accepted", school_id=inv.school_id, actor_user_id=user.id,
                 resource_type="user", resource_id=user.id, payload={"role": inv.role.value})
    db.commit()

    # auto-login: hand back a token pair so the demo flows straight into the app
    return {
        "access_token": create_access_token(user.id, user.role.value, user.school_id),
        "refresh_token": create_refresh_token(user.id),
        "token_type": "bearer",
        "user_id": str(user.id),
        "role": user.role.value,
    }
