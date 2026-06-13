from datetime import datetime
from sqlalchemy.orm import Session
from app.models import AuditEvent
import uuid

def run_reminder_engine(db: Session, correlation_id: str):
    current_hour = datetime.now().hour
    if current_hour >= 20 or current_hour < 8:
        log = AuditEvent(
            correlation_id=correlation_id,
            actor_id="SYSTEM_SCHEDULER",
            event_type="REMINDER_SKIPPED_QUIET_HOURS",
            payload={"message": "Skipping reminders. Policy active: Quiet Hours (8PM-8AM).", "current_hour": current_hour}
        )
        db.add(log)
        db.commit()
        return {"status": "SKIPPED", "reason": "QUIET_HOURS_ACTIVE"}


    students_state = [
        {"id": "student_01", "name": "Alex", "status": "BLOCKED", "phone": "+919999999901"},
        {"id": "student_02", "name": "Raja", "status": "SUBMITTED", "phone": "+919999999902"},
        {"id": "student_03", "name": "Suresh", "status": "SILENT", "phone": "+919999999903"}
    ]
    
    sent_reminders = []
    
    for student in students_state:
        if student["status"] == "SILENT":
            log = AuditEvent(
                correlation_id=correlation_id,
                actor_id="SYSTEM_SCHEDULER",
                event_type="REMINDER_SENT",
                payload={
                    "student_id": student["id"],
                    "student_name": student["name"],
                    "message": f"Hi {student['name']}, you have a pending math assignment due soon!"
                }
            )
            db.add(log)
            sent_reminders.append(student["name"])
            
    db.commit()
    
    return {
        "status": "COMPLETED",
        "processed_at": str(datetime.now()),
        "reminders_sent_to": sent_reminders
    }