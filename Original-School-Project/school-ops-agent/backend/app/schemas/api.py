"""
API DTOs (request/response models). Kept separate from ORM and from LLM schemas
so the HTTP contract can evolve independently.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import (
    AssignmentState,
    AssignmentTargetType,
    DocumentType,
    ReviewState,
    Role,
    SubmissionState,
)


# --- Auth ---
class RegisterSchoolRequest(BaseModel):
    school_name: str = Field(min_length=1, max_length=200)
    admin_name: str = Field(min_length=1, max_length=200)
    admin_email: str
    admin_password: str = Field(min_length=8, max_length=200)


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: Role
    school_id: uuid.UUID
    user_id: uuid.UUID
    full_name: str


# --- Invites ---
class CreateInviteRequest(BaseModel):
    role: Role
    email: EmailStr | None = None
    class_id: uuid.UUID | None = None
    target_student_id: uuid.UUID | None = None


class InviteResponse(BaseModel):
    invite_id: uuid.UUID
    token: str  # returned once
    role: Role
    expires_at: datetime


class AcceptInviteRequest(BaseModel):
    token: str
    full_name: str = Field(min_length=1, max_length=200)
    email: str | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)


# --- Classes ---
class CreateClassRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    grade_level: str | None = None


class ClassResponse(BaseModel):
    id: uuid.UUID
    name: str
    grade_level: str | None


class AssignTeacherRequest(BaseModel):
    teacher_id: uuid.UUID
    class_id: uuid.UUID


# --- Documents ---
class DocumentResponse(BaseModel):
    id: uuid.UUID
    doc_type: DocumentType
    filename: str
    review_state: ReviewState
    confidence: float | None
    ambiguities: list[str] | None
    clarifying_questions: list[str] | None
    parsed: dict | None


class ApproveParseRequest(BaseModel):
    # Optional corrected fields the reviewer edited before approving.
    overrides: dict | None = None


# --- Assignments ---
class CreateAssignmentRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    class_id: uuid.UUID | None = None
    subject: str | None = None
    instructions: str | None = None
    due_at: datetime | None = None
    target_type: AssignmentTargetType = AssignmentTargetType.CLASS


class AssignmentResponse(BaseModel):
    id: uuid.UUID
    title: str
    subject: str | None
    instructions: str | None
    due_at: datetime | None
    state: AssignmentState
    class_id: uuid.UUID | None


class TransitionRequest(BaseModel):
    to: str


# --- Submissions / feedback ---
class CreateSubmissionRequest(BaseModel):
    assignment_id: uuid.UUID
    body_text: str | None = None
    document_id: uuid.UUID | None = None


class FeedbackRequest(BaseModel):
    submission_id: uuid.UUID
    body: str = Field(min_length=1)
    decision: str | None = None  # "revision" | "complete" | None


class ProgressRequest(BaseModel):
    assignment_id: uuid.UUID
    blocked: bool = False
    note: str | None = None


# --- Audit ---
class AuditEventResponse(BaseModel):
    id: uuid.UUID
    created_at: datetime
    event_type: str
    summary: str
    actor_label: str | None
    correlation_id: str | None
    resource_type: str | None
    resource_id: str | None
    detail: dict | None
