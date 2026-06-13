"""
Document upload -> parse -> review -> approve flow (assignment briefs).

  POST /api/documents                    upload + parse; stored as approval_state=pending
  GET  /api/documents/{id}               review parsed fields, ambiguities, injection flags
  POST /api/documents/{id}/approve       confirm values + target -> creates the Assignment
  POST /api/documents/{id}/reject        discard the parse

Key boundaries:
  * The LLM parse is a PROPOSAL. Nothing is created until a human approves.
  * On approve the TEACHER supplies the final values + the real target (class/students);
    the model never resolves names to ids.
  * Uploads are idempotent by content hash -- re-uploading the same file returns the
    original document instead of creating a duplicate.
  * Model failures don't crash the upload: the doc is stored pending with an ambiguity
    note so it can be filled in manually (nothing is left silently stuck).
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import (
    ApprovalState,
    Assignment,
    AssignmentStatus,
    AssignmentTarget,
    DocType,
    Document,
    IdempotencyKey,
    SchoolClass,
    TargetType,
    User,
    UserRole,
)
from app.auth.deps import get_current_user, require_role, ensure_teacher_teaches_class
from app.agents.llm_client import LLMError
from app.documents.extract import extract_text
from app.documents.injection import scan_for_injection
from app.documents.parse_assignment import parse_assignment
from app.events import audit

router = APIRouter(prefix="/api/documents", tags=["documents"])

UPLOAD_DIR = "var/uploads"


# --- schemas ---

class DocumentOut(BaseModel):
    id: uuid.UUID
    doc_type: DocType
    approval_state: ApprovalState
    original_filename: str
    parsed: dict | None
    confidence_note: str | None
    injection_flags: list[str] = []
    duplicate: bool = False


class ApproveBody(BaseModel):
    # teacher may correct the parsed values:
    title: str
    subject: str | None = None
    instructions: str | None = None
    due_at: datetime | None = None
    # the real target (model never resolves these):
    target_type: TargetType
    class_id: uuid.UUID | None = None
    student_ids: list[uuid.UUID] | None = None
    group_label: str | None = None


# --- helpers ---

def _scope_check(db: Session, actor: User, doc: Document) -> None:
    if doc.school_id != actor.school_id:
        raise HTTPException(403, "Not permitted")
    if actor.role == UserRole.teacher and doc.class_id is not None:
        ensure_teacher_teaches_class(db, actor, doc.class_id)


# --- upload + parse ---

@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    class_id: uuid.UUID | None = Form(None),
    actor: User = Depends(require_role(UserRole.teacher, UserRole.admin)),
    db: Session = Depends(get_db),
) -> DocumentOut:
    data = await file.read()
    if len(data) > settings.UPLOAD_MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {settings.UPLOAD_MAX_MB}MB")

    # teacher may only attach to a class they teach
    if class_id is not None and actor.role == UserRole.teacher:
        ensure_teacher_teaches_class(db, actor, class_id)
    if class_id is not None:
        sc = db.get(SchoolClass, class_id)
        if sc is None or sc.school_id != actor.school_id:
            raise HTTPException(400, "class_id is not in your school")

    # idempotency: same content from same uploader -> return original
    digest = hashlib.sha256(
        f"{actor.school_id}:{actor.id}:".encode() + data
    ).hexdigest()
    existing_key = db.execute(
        select(IdempotencyKey).where(IdempotencyKey.key == digest)
    ).scalars().first()
    if existing_key and existing_key.result_ref:
        doc = db.get(Document, uuid.UUID(existing_key.result_ref))
        if doc is not None:
            return _to_out(doc, duplicate=True)

    text = extract_text(data, file.filename, file.content_type)  # may raise ValueError -> 400 below
    injection_flags = scan_for_injection(text)

    # parse (model failure must not crash the upload)
    try:
        draft = parse_assignment(text)
        parsed = draft.model_dump()
        confidence_note = f"confidence={draft.confidence}"
    except LLMError as e:
        parsed = {
            "title": None, "subject": None, "instructions": None, "due_date": None,
            "target_hint": None,
            "ambiguities": ["Automatic parsing failed; please fill in the fields manually."],
            "confidence": 0.0,
        }
        confidence_note = f"parse_error: {e}"
        audit.record(db, action="model.failed", school_id=actor.school_id, actor_user_id=actor.id,
                     resource_type="document", payload={"stage": "assignment_parse"})

    if injection_flags:
        parsed.setdefault("ambiguities", []).append(
            "This document contains text that looks like instructions to the system; review carefully."
        )

    # persist original file
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    doc_id = uuid.uuid4()
    ext = os.path.splitext(file.filename or "")[1]
    path = os.path.join(UPLOAD_DIR, f"{doc_id}{ext}")
    with open(path, "wb") as f:
        f.write(data)

    doc = Document(
        id=doc_id,
        school_id=actor.school_id,
        uploaded_by=actor.id,
        doc_type=DocType.assignment_brief,
        original_filename=file.filename or "upload",
        storage_path=path,
        parsed_json=parsed,
        confidence_note=confidence_note,
        approval_state=ApprovalState.pending,
        class_id=class_id,
    )
    db.add(doc)
    db.flush()

    db.add(IdempotencyKey(key=digest, scope="document_upload", result_ref=str(doc.id)))
    audit.record(db, action="document.parsed", school_id=actor.school_id, actor_user_id=actor.id,
                 resource_type="document", resource_id=doc.id,
                 payload={"injection_flags": len(injection_flags)})
    db.commit()

    return _to_out(doc, injection_flags=injection_flags)


# --- review ---

@router.get("/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: uuid.UUID,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentOut:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    _scope_check(db, actor, doc)
    return _to_out(doc)


# --- approve -> create Assignment ---

@router.post("/{document_id}/approve")
def approve_document(
    document_id: uuid.UUID,
    body: ApproveBody,
    actor: User = Depends(require_role(UserRole.teacher, UserRole.admin)),
    db: Session = Depends(get_db),
) -> dict:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    _scope_check(db, actor, doc)
    if doc.approval_state != ApprovalState.pending:
        raise HTTPException(409, f"Document already {doc.approval_state.value}")

    # validate target
    if body.target_type == TargetType.klass:
        if body.class_id is None:
            raise HTTPException(400, "class_id required for a class target")
        sc = db.get(SchoolClass, body.class_id)
        if sc is None or sc.school_id != actor.school_id:
            raise HTTPException(400, "class_id not in your school")
    elif body.target_type in (TargetType.individual, TargetType.group):
        if not body.student_ids:
            raise HTTPException(400, "student_ids required for individual/group target")

    assignment = Assignment(
        school_id=actor.school_id,
        created_by=actor.id,
        source_document_id=doc.id,
        title=body.title,
        subject=body.subject,
        instructions=body.instructions,
        due_at=body.due_at,
        status=AssignmentStatus.active,
    )
    db.add(assignment)
    db.flush()

    if body.target_type == TargetType.klass:
        db.add(AssignmentTarget(assignment_id=assignment.id, target_type=TargetType.klass,
                                class_id=body.class_id))
    else:
        for sid in body.student_ids:
            db.add(AssignmentTarget(assignment_id=assignment.id, target_type=body.target_type,
                                    student_id=sid, group_label=body.group_label))

    doc.approval_state = ApprovalState.approved
    doc.assignment_id = assignment.id

    audit.record(db, action="assignment.created", school_id=actor.school_id, actor_user_id=actor.id,
                 resource_type="assignment", resource_id=assignment.id,
                 payload={"from_document": str(doc.id), "target_type": body.target_type.value})
    audit.record(db, action="document.approved", school_id=actor.school_id, actor_user_id=actor.id,
                 resource_type="document", resource_id=doc.id)
    db.commit()

    return {"assignment_id": str(assignment.id), "status": assignment.status.value}


# --- reject ---

@router.post("/{document_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
def reject_document(
    document_id: uuid.UUID,
    actor: User = Depends(require_role(UserRole.teacher, UserRole.admin)),
    db: Session = Depends(get_db),
) -> None:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    _scope_check(db, actor, doc)
    if doc.approval_state != ApprovalState.pending:
        raise HTTPException(409, f"Document already {doc.approval_state.value}")
    doc.approval_state = ApprovalState.rejected
    audit.record(db, action="document.rejected", school_id=actor.school_id, actor_user_id=actor.id,
                 resource_type="document", resource_id=doc.id)
    db.commit()


def _to_out(doc: Document, *, injection_flags: list[str] | None = None, duplicate: bool = False) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        doc_type=doc.doc_type,
        approval_state=doc.approval_state,
        original_filename=doc.original_filename,
        parsed=doc.parsed_json,
        confidence_note=doc.confidence_note,
        injection_flags=injection_flags or [],
        duplicate=duplicate,
    )
