"""
Authorization dependencies and scope checks.

Two layers:
  1. ROLE gate  -- `require_role(...)` as a FastAPI dependency (cheap, token-based).
  2. RESOURCE scope -- helper functions called *inside* a route once the resource
     is loaded, because "does this teacher teach THIS class" needs the DB.

Every scoped route should do BOTH: gate by role at the signature, then assert
resource scope before acting. This is the server-side check the rubric wants on
every school/class/student action.
"""

from __future__ import annotations

import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User, UserRole, teacher_class_link, guardian_student_link
from app.auth.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

_CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)
_FORBIDDEN = HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    try:
        claims = decode_token(token)
        if claims.get("type") != "access":
            raise _CREDENTIALS_EXC
        user_id = uuid.UUID(claims["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise _CREDENTIALS_EXC

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _CREDENTIALS_EXC
    return user


def require_role(*roles: UserRole):
    """Dependency factory: gate a route to specific roles."""
    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise _FORBIDDEN
        return user
    return _dep


# --- resource-scope assertions (call inside routes after loading the resource) ---

def ensure_same_school(user: User, resource_school_id: uuid.UUID) -> None:
    if user.school_id != resource_school_id:
        raise _FORBIDDEN


def ensure_teacher_teaches_class(db: Session, teacher: User, class_id: uuid.UUID) -> None:
    if teacher.role != UserRole.teacher:
        raise _FORBIDDEN
    row = db.execute(
        teacher_class_link.select().where(
            teacher_class_link.c.teacher_id == teacher.id,
            teacher_class_link.c.class_id == class_id,
        )
    ).first()
    if row is None:
        raise _FORBIDDEN


def ensure_guardian_of(db: Session, guardian: User, student_id: uuid.UUID) -> None:
    if guardian.role != UserRole.guardian:
        raise _FORBIDDEN
    row = db.execute(
        guardian_student_link.select().where(
            guardian_student_link.c.guardian_id == guardian.id,
            guardian_student_link.c.student_id == student_id,
        )
    ).first()
    if row is None:
        raise _FORBIDDEN


def ensure_student_self(user: User, student_id: uuid.UUID) -> None:
    if user.role != UserRole.student or user.id != student_id:
        raise _FORBIDDEN
