"""
Auth + registration routes.

Flow:
  POST /api/auth/register  -> create a School + its first admin user (one txn)
  POST /api/auth/login     -> verify password, issue access + refresh tokens
  POST /api/auth/refresh   -> exchange a refresh token for a new access token
  GET  /api/auth/me        -> the authenticated user

Logout is client-side (drop the tokens). For server-side revocation you'd add a
token denylist in Redis -- noted as a known limitation in the README.
"""

from __future__ import annotations

import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import School, User, UserRole
from app.auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.auth.deps import get_current_user
from app.events import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


# --- schemas ---

class RegisterSchool(BaseModel):
    school_name: str
    admin_full_name: str
    admin_email: EmailStr
    admin_password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: uuid.UUID
    school_id: uuid.UUID
    role: UserRole
    full_name: str
    email: str | None

    class Config:
        from_attributes = True


class RefreshIn(BaseModel):
    refresh_token: str


# --- routes ---

@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def register_school(body: RegisterSchool, db: Session = Depends(get_db)) -> TokenPair:
    school = School(name=body.school_name)
    db.add(school)
    db.flush()  # need school.id

    admin = User(
        school_id=school.id,
        role=UserRole.admin,
        email=str(body.admin_email),
        hashed_password=hash_password(body.admin_password),
        full_name=body.admin_full_name,
    )
    db.add(admin)
    db.flush()

    audit.record(db, action="school.registered", school_id=school.id, actor_user_id=admin.id,
                 resource_type="school", resource_id=school.id)
    audit.record(db, action="user.registered", school_id=school.id, actor_user_id=admin.id,
                 resource_type="user", resource_id=admin.id, payload={"role": "admin"})
    db.commit()

    return TokenPair(
        access_token=create_access_token(admin.id, admin.role.value, school.id),
        refresh_token=create_refresh_token(admin.id),
    )


@router.post("/login", response_model=TokenPair)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> TokenPair:
    # `username` carries the email. NOTE: email is unique per-school, so if the
    # same email exists at two schools this picks the first; documented limitation.
    user = db.execute(
        select(User).where(User.email == form.username, User.is_active.is_(True))
    ).scalars().first()

    if user is None or not user.hashed_password or not verify_password(form.password, user.hashed_password):
        # audit the failure without leaking which part was wrong
        audit.record(db, action="auth.login_failed", payload={"email_present": user is not None})
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    audit.record(db, action="auth.login", school_id=user.school_id, actor_user_id=user.id)
    db.commit()
    return TokenPair(
        access_token=create_access_token(user.id, user.role.value, user.school_id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshIn, db: Session = Depends(get_db)) -> TokenPair:
    try:
        claims = decode_token(body.refresh_token)
        if claims.get("type") != "refresh":
            raise ValueError("wrong token type")
        user = db.get(User, uuid.UUID(claims["sub"]))
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    return TokenPair(
        access_token=create_access_token(user.id, user.role.value, user.school_id),
        refresh_token=create_refresh_token(user.id),
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
