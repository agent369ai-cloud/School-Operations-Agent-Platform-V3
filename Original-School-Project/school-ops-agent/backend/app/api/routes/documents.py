"""Document routes: upload, parse, review, approve. Idempotent on file bytes."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_auth_context
from app.core.authz import AuthContext, require_admin
from app.core.config import get_settings
from app.core.security import sha256_bytes
from app.db.base import get_db
from app.models.core import Enrollment, GuardianStudentLink, SchoolClass, User
from app.models.enums import AuditEventType, DocumentType, ReviewState, Role
from app.models.operations import Document
from app.parsers.extract import ExtractionError, extract_text
from app.parsers.pipeline import parse_document
from app.schemas.api import ApproveParseRequest, DocumentResponse
from app.services.audit import record_event

router = APIRouter(prefix="/documents", tags=["documents"])
settings = get_settings()


def _to_response(doc: Document) -> DocumentResponse:
    return DocumentResponse(
        id=doc.id, doc_type=doc.doc_type, filename=doc.filename,
        review_state=doc.review_state, confidence=doc.confidence,
        ambiguities=doc.ambiguities, clarifying_questions=doc.clarifying_questions,
        parsed=doc.parsed,
    )


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    doc_type: DocumentType = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    if ctx.role not in (Role.ADMIN, Role.TEACHER):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only staff upload documents")
    data = await file.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file too large")
    import os
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in settings.allowed_upload_extensions_list:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"extension {ext} not allowed")

    content_hash = sha256_bytes(data)
    # Idempotent re-upload: same bytes + type in same school -> return existing.
    existing = db.query(Document).filter(
        Document.school_id == ctx.school_id,
        Document.content_hash == content_hash,
        Document.doc_type == doc_type,
    ).one_or_none()
    if existing:
        return _to_response(existing)

    # Persist bytes to disk (safe filename derived from doc id).
    os.makedirs(settings.upload_dir, exist_ok=True)
    doc = Document(
        school_id=ctx.school_id, uploaded_by=ctx.user_id, doc_type=doc_type,
        filename=file.filename or "upload", content_type=file.content_type,
        content_hash=content_hash, review_state=ReviewState.PENDING_PARSE,
    )
    db.add(doc)
    db.flush()
    storage_path = os.path.join(settings.upload_dir, f"{doc.id}{ext}")
    with open(storage_path, "wb") as fh:
        fh.write(data)
    doc.storage_path = storage_path

    record_event(
        db, event_type=AuditEventType.DOCUMENT_UPLOADED,
        summary=f"Uploaded {doc_type.value}: {doc.filename}",
        school_id=ctx.school_id, actor_user_id=ctx.user_id,
        resource_type="document", resource_id=doc.id,
    )

    # Extract + parse synchronously (small docs; keeps the demo simple).
    try:
        raw_text = extract_text(data=data, filename=doc.filename,
                                content_type=doc.content_type)
        doc.raw_text = raw_text
    except ExtractionError as exc:
        doc.review_state = ReviewState.FAILED
        doc.ambiguities = [str(exc)]
        record_event(
            db, event_type=AuditEventType.MODEL_FAILURE,
            summary=f"Extraction failed for {doc.filename}",
            school_id=ctx.school_id, resource_type="document", resource_id=doc.id,
            detail={"error": str(exc)},
        )
        return _to_response(doc)

    outcome = parse_document(doc_type, raw_text)
    doc.parsed = outcome.parsed
    doc.confidence = outcome.confidence
    doc.ambiguities = outcome.ambiguities
    doc.clarifying_questions = outcome.clarifying_questions
    doc.review_state = outcome.review_state
    db.add(doc)
    record_event(
        db, event_type=AuditEventType.DOCUMENT_PARSED,
        summary=f"Parsed {doc_type.value}; state={outcome.review_state.value}",
        school_id=ctx.school_id, actor_user_id=ctx.user_id,
        resource_type="document", resource_id=doc.id,
        detail={"confidence": outcome.confidence,
                "ambiguity_count": len(outcome.ambiguities)},
    )
    return _to_response(doc)


@router.post("/student-upload", status_code=201)
async def student_upload(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    """Students upload their submission files (PDF / image). Returns a document_id
    to attach to the subsequent POST /submissions call."""
    if ctx.role != Role.STUDENT:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "students only")
    data = await file.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file too large")
    import os
    ext = os.path.splitext(file.filename or "")[1].lower()
    allowed = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp"}
    if ext not in allowed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"only PDF or images allowed, got {ext}")

    content_hash = sha256_bytes(data)
    existing = db.query(Document).filter(
        Document.school_id == ctx.school_id,
        Document.content_hash == content_hash,
        Document.doc_type == DocumentType.STUDENT_SUBMISSION,
    ).one_or_none()
    if existing:
        return {"document_id": str(existing.id), "filename": existing.filename}

    os.makedirs(settings.upload_dir, exist_ok=True)
    doc = Document(
        school_id=ctx.school_id, uploaded_by=ctx.user_id,
        doc_type=DocumentType.STUDENT_SUBMISSION,
        filename=file.filename or "submission",
        content_type=file.content_type,
        content_hash=content_hash,
        review_state=ReviewState.APPROVED,  # student submissions don't need staff review
    )
    db.add(doc)
    db.flush()
    storage_path = os.path.join(settings.upload_dir, f"{doc.id}{ext}")
    with open(storage_path, "wb") as fh:
        fh.write(data)
    doc.storage_path = storage_path
    record_event(
        db, event_type=AuditEventType.DOCUMENT_UPLOADED,
        summary=f"Student uploaded submission file: {doc.filename}",
        school_id=ctx.school_id, actor_user_id=ctx.user_id,
        resource_type="document", resource_id=doc.id,
    )
    return {"document_id": str(doc.id), "filename": doc.filename}


@router.get("", response_model=list[DocumentResponse])
def list_documents(
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    rows = db.query(Document).filter(Document.school_id == ctx.school_id).all()
    return [_to_response(d) for d in rows]


@router.post("/{document_id}/approve", response_model=DocumentResponse)
def approve_parse(
    document_id: uuid.UUID,
    body: ApproveParseRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    doc = db.get(Document, document_id)
    if not doc or doc.school_id != ctx.school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    if ctx.role not in (Role.ADMIN, Role.TEACHER):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only staff approve")
    if doc.review_state == ReviewState.APPROVED:
        return _to_response(doc)  # idempotent

    # Apply reviewer overrides (their corrections to ambiguous fields).
    if body.overrides:
        merged = dict(doc.parsed or {})
        merged.update(body.overrides)
        doc.parsed = merged

    doc.review_state = ReviewState.APPROVED
    doc.reviewed_by = ctx.user_id
    doc.reviewed_at = datetime.now(timezone.utc)
    db.add(doc)
    record_event(
        db, event_type=AuditEventType.PARSE_APPROVED,
        summary=f"Parse approved for {doc.filename}",
        school_id=ctx.school_id, actor_user_id=ctx.user_id,
        resource_type="document", resource_id=doc.id,
    )

    # Side effects on approval:
    if doc.doc_type == DocumentType.CLASS_ROSTER:
        _import_roster(db, ctx, doc)
    elif doc.doc_type == DocumentType.SCHOOL_POLICY and doc.parsed:
        pass  # policy docs are reviewed; admin applies via /admin/policy
    return _to_response(doc)


@router.get("/{document_id}/file")
def download_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    token: str | None = None,          # ?token= for browser tab opens
    authorization: str | None = None,  # Header("Authorization") via Header()
    ctx: AuthContext | None = None,
):
    """Serve the raw uploaded file. Accepts bearer token via header OR ?token= query param
    so the browser can open the file in a new tab without JS fetch."""
    import os
    from fastapi import Header as _Header
    from app.core.security import decode_access_token
    from app.models.core import User as _User

    # Resolve token from either source
    raw_token = token
    if not raw_token and authorization and authorization.lower().startswith("bearer "):
        raw_token = authorization.split(" ", 1)[1]
    if not raw_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")

    payload = decode_access_token(raw_token)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")

    user = db.get(_User, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")

    doc = db.get(Document, document_id)
    if not doc or str(doc.school_id) != str(user.school_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    if user.role == Role.STUDENT and str(doc.uploaded_by) != str(user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your document")
    if not doc.storage_path or not os.path.exists(doc.storage_path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file not found on disk")

    return FileResponse(
        doc.storage_path,
        media_type=doc.content_type or "application/octet-stream",
        filename=doc.filename,
    )


@router.post("/{document_id}/reject", response_model=DocumentResponse)
def reject_parse(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    doc = db.get(Document, document_id)
    if not doc or doc.school_id != ctx.school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    doc.review_state = ReviewState.REJECTED
    doc.reviewed_by = ctx.user_id
    doc.reviewed_at = datetime.now(timezone.utc)
    db.add(doc)
    record_event(
        db, event_type=AuditEventType.PARSE_REJECTED,
        summary=f"Parse rejected for {doc.filename}",
        school_id=ctx.school_id, actor_user_id=ctx.user_id,
        resource_type="document", resource_id=doc.id,
    )
    return _to_response(doc)


def _import_roster(db: Session, ctx: AuthContext, doc: Document) -> None:
    """Create student users + enrollments from an approved roster. Best-effort
    matching of class name to an existing class in the school."""
    rows = (doc.parsed or {}).get("rows", [])
    classes = {c.name.lower(): c for c in db.query(SchoolClass).filter(
        SchoolClass.school_id == ctx.school_id
    )}
    created = 0
    for row in rows:
        name = (row.get("name") or "").strip()
        if not name:
            continue
        klass_name = (row.get("class") or "").strip().lower()
        sc = classes.get(klass_name)
        # Skip duplicates by (school, name, role=student).
        existing = db.query(User).filter(
            User.school_id == ctx.school_id, User.full_name == name,
            User.role == Role.STUDENT,
        ).first()
        student = existing or User(
            school_id=ctx.school_id, role=Role.STUDENT, full_name=name,
        )
        if not existing:
            db.add(student)
            db.flush()
            created += 1
        if sc:
            already = db.query(Enrollment).filter(
                Enrollment.student_id == student.id, Enrollment.class_id == sc.id
            ).first()
            if not already:
                db.add(Enrollment(
                    school_id=ctx.school_id, student_id=student.id, class_id=sc.id
                ))
    record_event(
        db, event_type=AuditEventType.PARSE_APPROVED,
        summary=f"Roster imported: {created} new students",
        school_id=ctx.school_id, actor_user_id=ctx.user_id,
        resource_type="document", resource_id=doc.id,
        detail={"created": created, "rows": len(rows)},
    )
