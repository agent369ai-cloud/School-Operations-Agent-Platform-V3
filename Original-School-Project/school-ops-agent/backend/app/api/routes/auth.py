"""Auth + onboarding routes: register school, login, invites, accept invite."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    generate_invite_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.db.base import get_db
from app.models.core import (
    Enrollment,
    GuardianStudentLink,
    Invite,
    School,
    TeacherClassLink,
    User,
)
from app.models.enums import AuditEventType, InviteStatus, Role
from app.schemas.api import (
    AcceptInviteRequest,
    CreateInviteRequest,
    InviteResponse,
    LoginRequest,
    RegisterSchoolRequest,
    TokenResponse,
)
from app.services.audit import record_event

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


@router.post("/register", response_model=TokenResponse, status_code=201)
def register_school(body: RegisterSchoolRequest, db: Session = Depends(get_db)):
    # One admin account bootstraps one school.
    school = School(name=body.school_name, policy={})
    db.add(school)
    db.flush()
    admin = User(
        school_id=school.id, role=Role.ADMIN, email=body.admin_email,
        full_name=body.admin_name, hashed_password=hash_password(body.admin_password),
    )
    db.add(admin)
    db.flush()
    record_event(
        db, event_type=AuditEventType.REGISTRATION,
        summary=f"School '{school.name}' registered",
        school_id=school.id, actor_user_id=admin.id,
        resource_type="school", resource_id=school.id,
    )
    role_str = admin.role.value if hasattr(admin.role, "value") else str(admin.role)
    token = create_access_token(
        subject=str(admin.id), role=role_str, school_id=str(school.id)
    )
    return TokenResponse(
        access_token=token, role=role_str, school_id=school.id,
        user_id=admin.id, full_name=admin.full_name,
    )


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    # Use first() — the same email can legally exist across different schools
    # (unique constraint is per school_id+email). first() avoids MultipleResultsFound.
    user = db.query(User).filter(User.email == body.email).first()
    if user is None or not user.hashed_password or not verify_password(
        body.password, user.hashed_password
    ):
        # Audit the failure without revealing which factor was wrong.
        if user is not None:
            record_event(
                db, event_type=AuditEventType.LOGIN_FAILED,
                summary="Failed login attempt", school_id=user.school_id,
                actor_user_id=user.id,
            )
            db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    record_event(
        db, event_type=AuditEventType.LOGIN, summary="User logged in",
        school_id=user.school_id, actor_user_id=user.id,
    )
    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    token = create_access_token(
        subject=str(user.id), role=role_str, school_id=str(user.school_id)
    )
    return TokenResponse(
        access_token=token, role=role_str, school_id=user.school_id,
        user_id=user.id, full_name=user.full_name,
    )


@router.post("/invites", response_model=InviteResponse, status_code=201)
def create_invite(
    body: CreateInviteRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    # Only admins invite teachers; teachers/admins invite students+guardians.
    if body.role == Role.TEACHER and actor.role != Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only admins invite teachers")
    if actor.role not in (Role.ADMIN, Role.TEACHER):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not allowed to invite")
    # Scope the invite to the actor's school. class/target must be in-school.
    raw = generate_invite_token()
    invite = Invite(
        school_id=actor.school_id,
        token_hash=hash_token(raw),
        role=body.role,
        email=body.email,
        class_id=body.class_id,
        target_student_id=body.target_student_id,
        status=InviteStatus.PENDING,
        expires_at=datetime.now(timezone.utc)
        + timedelta(hours=settings.invite_token_ttl_hours),
    )
    db.add(invite)
    db.flush()
    record_event(
        db, event_type=AuditEventType.INVITE_CREATED,
        summary=f"Invite created for role {body.role}",
        school_id=actor.school_id, actor_user_id=actor.id,
        resource_type="invite", resource_id=invite.id,
        detail={"role": str(body.role), "class_id": str(body.class_id) if body.class_id else None},
    )
    return InviteResponse(
        invite_id=invite.id, token=raw, role=invite.role, expires_at=invite.expires_at
    )


@router.post("/invites/accept", response_model=TokenResponse, status_code=201)
def accept_invite(body: AcceptInviteRequest, db: Session = Depends(get_db)):
    invite = db.query(Invite).filter(
        Invite.token_hash == hash_token(body.token)
    ).one_or_none()
    if invite is None or invite.status != InviteStatus.PENDING:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid or used invite")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if invite.expires_at < now:
        invite.status = InviteStatus.EXPIRED
        db.add(invite)
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invite expired")

    # Teachers/admins authenticate with a password; students/guardians may not.
    hashed = None
    if invite.role in (Role.ADMIN, Role.TEACHER):
        if not body.password:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "password required")
        hashed = hash_password(body.password)
    elif body.password:
        hashed = hash_password(body.password)

    user = User(
        school_id=invite.school_id, role=invite.role,
        email=body.email or invite.email,
        full_name=body.full_name, hashed_password=hashed,
    )
    db.add(user)
    db.flush()

    # Apply scoped linking based on invite role + scope.
    if invite.role == Role.TEACHER and invite.class_id:
        db.add(TeacherClassLink(
            school_id=invite.school_id, teacher_id=user.id, class_id=invite.class_id
        ))
    elif invite.role == Role.STUDENT and invite.class_id:
        db.add(Enrollment(
            school_id=invite.school_id, student_id=user.id, class_id=invite.class_id
        ))
    elif invite.role == Role.GUARDIAN and invite.target_student_id:
        db.add(GuardianStudentLink(
            school_id=invite.school_id, guardian_id=user.id,
            student_id=invite.target_student_id, opted_in=False,
        ))

    invite.status = InviteStatus.ACCEPTED
    invite.accepted_user_id = user.id
    db.add(invite)
    record_event(
        db, event_type=AuditEventType.INVITE_ACCEPTED,
        summary=f"Invite accepted; {invite.role} onboarded",
        school_id=invite.school_id, actor_user_id=user.id,
        resource_type="user", resource_id=user.id,
    )
    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    token = create_access_token(
        subject=str(user.id), role=role_str, school_id=str(user.school_id)
    )
    return TokenResponse(
        access_token=token, role=role_str, school_id=user.school_id,
        user_id=user.id, full_name=user.full_name,
    )
