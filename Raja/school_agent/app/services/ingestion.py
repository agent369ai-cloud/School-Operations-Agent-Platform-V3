# app/routers/ingestion.py
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.ai_parser import parse_assignment_brief
from app.models import Assignment, AuditEvent
import uuid

router = APIRouter()

@router.post("/upload-brief")
async def upload_assignment_brief(
    file: UploadFile = File(...), 
    classroom_id: str = "grade-7-a", # Mock default for rapid demo execution
    db: Session = Depends(get_db)
):
    # 1. Read the uploaded file contents
    contents = await file.read()
    document_text = contents.decode("utf-8")
    
    # 2. Trigger request correlation identifier tracking 
    correlation_id = str(uuid.uuid4())
    
    # 3. Call your proxy OpenAI structured parser
    try:
        parsed_data = parse_assignment_brief(document_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Engine Extraction failed: {str(e)}")
    
    # 4. Record the parsing event to your immutable audit log tracking engine
    audit_log = AuditEvent(
        correlation_id=correlation_id,
        actor_id="teacher-1",
        event_type="ASSIGNMENT_BRIEF_PARSED",
        payload={
            "filename": file.filename,
            "extracted_title": parsed_data.title,
            "is_ambiguous": parsed_data.is_ambiguous
        }
    )
    db.add(audit_log)
    
    # 5. Execute "Model-as-Proposal" logic state routing
    if parsed_data.is_ambiguous:
        # Save a temporary draft row with missing elements flag active
        new_assignment = Assignment(
            id=str(uuid.uuid4()),
            classroom_id=classroom_id,
            title=parsed_data.title,
            instructions=parsed_data.instructions,
            due_date=None, # Explicitly missing
            status="DRAFT"
        )
        db.add(new_assignment)
        db.commit()
        
        # Return structured review state payload triggering conditional UI dialog fields
        return {
            "status": "REQUIRES_CLARIFICATION",
            "assignment_id": new_assignment.id,
            "correlation_id": correlation_id,
            "message": parsed_data.clarification_question,
            "extracted_draft": {
                "title": parsed_data.title,
                "subject": parsed_data.subject,
                "instructions": parsed_data.instructions
            }
        }
    
    # If the document is clean and fully formed, commit immediately as operational state
    new_assignment = Assignment(
        id=str(uuid.uuid4()),
        classroom_id=classroom_id,
        title=parsed_data.title,
        instructions=parsed_data.instructions,
        status="APPROVED"
    )
    db.add(new_assignment)
    db.commit()
    
    return {"status": "SUCCESSFULLY_CREATED", "assignment_id": new_assignment.id, "correlation_id": correlation_id}
