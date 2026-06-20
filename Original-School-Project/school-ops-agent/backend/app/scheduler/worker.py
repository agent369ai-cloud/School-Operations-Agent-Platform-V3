"""
Reminder scheduler.

A background thread wakes every ``scheduler_tick_seconds`` and runs a sweep.
Restart-safety comes from three properties:

  1. State lives in the database, not in memory. On boot the scheduler simply
     resumes sweeping; no in-memory timers are lost.
  2. Reminders are idempotent: each (assignment_target, dedup_key) is unique,
     so a sweep that runs twice (or after a crash mid-sweep) never double-sends.
  3. Every send/suppress writes a Reminder row + audit event, so an operator
     can see exactly what happened and why — including after a restart.

The ``run_sweep`` function is also exposed for the manual demo trigger
(POST /reminders/run), so the interview scenario can fire it on demand.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger, set_correlation_id
from app.db.base import SessionLocal
from app.models.enums import AuditEventType, StudentProgressState
from app.models.operations import (
    Assignment,
    AssignmentTarget,
    Reminder,
)
from app.models.core import ChatIdentity, School
from app.channels.adapter import get_adapter
from app.scheduler.policy import decide
from app.services.audit import record_event

log = get_logger("scheduler")
settings = get_settings()


def _today_key(now: datetime) -> str:
    return f"sweep:{now.strftime('%Y-%m-%d-%H')}"  # one reminder per target per hour


def run_sweep(db: Session, *, now: datetime | None = None, manual: bool = False) -> dict:
    """Run one reminder sweep. Returns a summary for the manual trigger."""
    now = now or datetime.now(timezone.utc)
    set_correlation_id(None)  # fresh correlation id for this sweep
    dedup_key = _today_key(now)

    sent = 0
    suppressed = 0
    escalated = 0

    # Only consider targets for active assignments that are not done.
    targets = (
        db.query(AssignmentTarget)
        .join(Assignment, Assignment.id == AssignmentTarget.assignment_id)
        .filter(
            AssignmentTarget.progress_state.notin_(
                [StudentProgressState.SUBMITTED, StudentProgressState.COMPLETED]
            )
        )
        .all()
    )

    # Cache school policies.
    policy_cache: dict[str, dict] = {}

    for target in targets:
        assignment = db.get(Assignment, target.assignment_id)
        if assignment is None:
            continue
        sid = str(target.school_id)
        if sid not in policy_cache:
            school = db.get(School, target.school_id)
            policy_cache[sid] = (school.policy if school else {}) or {}
        policy = policy_cache[sid]

        decision = decide(
            progress_state=target.progress_state,
            reminder_count=target.reminder_count,
            due_at=assignment.due_at,
            now_utc=now,
            school_policy=policy,
            assignment_title=assignment.title,
        )

        # Idempotency: try to claim a reminder row for this (target, dedup_key).
        reminder = Reminder(
            school_id=target.school_id,
            assignment_target_id=target.id,
            scheduled_for=now,
            dedup_key=dedup_key,
            suppressed=not decision.should_send,
            suppression_reason=None if decision.should_send else decision.reason,
            body=decision.body,
        )
        db.add(reminder)
        try:
            db.flush()
        except IntegrityError:
            # Already reminded this target this hour — skip silently (restart-safe).
            db.rollback()
            continue

        if not decision.should_send:
            suppressed += 1
            record_event(
                db,
                event_type=AuditEventType.REMINDER_SUPPRESSED,
                summary=f"Reminder suppressed ({decision.reason}) for '{assignment.title}'",
                school_id=target.school_id,
                actor_label="scheduler",
                resource_type="assignment_target",
                resource_id=target.id,
                detail={"reason": decision.reason},
            )
            continue

        # Deliver via the student's verified chat identity if present.
        identity = (
            db.query(ChatIdentity)
            .filter(
                ChatIdentity.user_id == target.student_id,
                ChatIdentity.verified.is_(True),
            )
            .first()
        )
        if identity and decision.body:
            get_adapter(identity.channel).send(
                external_user_id=identity.external_id, text=decision.body
            )

        target.reminder_count += 1
        target.last_reminded_at = now
        reminder.sent_at = now
        db.add(target)
        db.add(reminder)
        sent += 1
        if decision.escalate:
            escalated += 1
        record_event(
            db,
            event_type=AuditEventType.REMINDER_SENT,
            summary=f"Reminder sent ({decision.reason}) for '{assignment.title}'",
            school_id=target.school_id,
            actor_label="scheduler",
            resource_type="assignment_target",
            resource_id=target.id,
            detail={"reason": decision.reason, "escalate": decision.escalate,
                    "reminder_count": target.reminder_count},
        )

    db.commit()
    summary = {"sent": sent, "suppressed": suppressed, "escalated": escalated,
               "manual": manual, "at": now.isoformat()}
    log.info("sweep_complete", extra=summary)
    return summary


class SchedulerThread(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True, name="reminder-scheduler")
        self._stop_event = threading.Event()

    def run(self) -> None:
        log.info("scheduler_started",
                 extra={"tick_seconds": settings.scheduler_tick_seconds})
        while not self._stop_event.is_set():
            try:
                db = SessionLocal()
                try:
                    run_sweep(db)
                finally:
                    db.close()
            except Exception as exc:  # pragma: no cover - keep the loop alive
                log.warning("sweep_error", extra={"error": str(exc)})
            self._stop_event.wait(settings.scheduler_tick_seconds)

    def stop(self) -> None:
        self._stop_event.set()


_thread: SchedulerThread | None = None


def start_scheduler() -> None:
    global _thread
    if _thread is None or not _thread.is_alive():
        _thread = SchedulerThread()
        _thread.start()


def stop_scheduler() -> None:
    if _thread is not None:
        _thread.stop()
