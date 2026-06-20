"""
FastAPI dependencies: authentication + AuthContext resolution.

``get_current_user`` validates the bearer token and loads the user. 
``get_auth_context`` augments it with the class/student scope the policy engine
needs. Route handlers depend on ``get_auth_context`` and then call the pure
policy functions in ``app.core.authz``.
"""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.authz import AuthContext
from app.core.security import decode_access_token
from app.db.base import get_db
from app.models.core import Enrollment, GuardianStudentLink, TeacherClassLink, User
from app.models.enums import Role


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = authorization.split(" ", 1)[1]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")
    user = db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found or inactive")
    # Defense in depth: token school must match the stored user's school.
    if str(user.school_id) != payload.get("school_id"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token/user school mismatch")
    return user


def get_auth_context(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuthContext:
    class_ids: set = set()
    student_ids: set = set()
    if user.role == Role.TEACHER:
        class_ids = {
            l.class_id for l in db.query(TeacherClassLink).filter(
                TeacherClassLink.teacher_id == user.id
            )
        }
    elif user.role == Role.STUDENT:
        class_ids = {
            e.class_id for e in db.query(Enrollment).filter(
                Enrollment.student_id == user.id
            )
        }
    elif user.role == Role.GUARDIAN:
        student_ids = {
            g.student_id for g in db.query(GuardianStudentLink).filter(
                GuardianStudentLink.guardian_id == user.id,
                GuardianStudentLink.opted_in.is_(True),
            )
        }
    return AuthContext(
        user_id=user.id, school_id=user.school_id, role=user.role,
        class_ids=frozenset(class_ids), student_ids=frozenset(student_ids),
    )


def require_roles(*roles: Role):
    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "role not permitted")
        return user
    return _dep
