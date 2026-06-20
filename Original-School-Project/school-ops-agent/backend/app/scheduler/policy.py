"""
Reminder policy engine (deterministic, model-free).

This is pure business logic intentionally kept out of the LLM path: reminder
decisions must be predictable and auditable. Given an assignment target and the
school policy, it decides whether to send, suppress, or escalate — and records
a reason either way.

Policy shape (stored as School.policy JSON), with safe defaults:
{
  "quiet_hours": {"start": 21, "end": 7},   # local 24h; inclusive start..end
  "timezone_offset_minutes": 0,             # minutes from UTC
  "max_reminders": 3,
  "escalate_after": 2,                       # reminders before guardian escalation
  "remind_blocked": true,                    # do we nudge blocked students?
  "allowed_channels": ["telegram"]
}
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.models.enums import StudentProgressState

DEFAULT_POLICY = {
    "quiet_hours": {"start": 21, "end": 7},
    "timezone_offset_minutes": 0,
    "max_reminders": 3,
    "escalate_after": 2,
    "remind_blocked": True,
    "allowed_channels": ["telegram"],
}


@dataclass
class ReminderDecision:
    should_send: bool
    escalate: bool
    reason: str
    body: str | None = None


def _merged_policy(school_policy: dict | None) -> dict:
    policy = dict(DEFAULT_POLICY)
    if school_policy:
        for k, v in school_policy.items():
            policy[k] = v
    return policy


def in_quiet_hours(now_utc: datetime, policy: dict) -> bool:
    offset = timedelta(minutes=policy.get("timezone_offset_minutes", 0))
    local = now_utc + offset
    hour = local.hour
    start = policy["quiet_hours"]["start"]
    end = policy["quiet_hours"]["end"]
    if start <= end:
        return start <= hour < end
    # Wraps midnight, e.g. 21..7
    return hour >= start or hour < end


def decide(
    *,
    progress_state: StudentProgressState,
    reminder_count: int,
    due_at: datetime | None,
    now_utc: datetime,
    school_policy: dict | None,
    assignment_title: str,
) -> ReminderDecision:
    """Core decision. Differentiates silent / blocked / submitted students per
    the brief's scenario step 5."""
    policy = _merged_policy(school_policy)

    # Submitted/completed students are never reminded.
    if progress_state in (StudentProgressState.SUBMITTED, StudentProgressState.COMPLETED):
        return ReminderDecision(False, False, "already_submitted")

    # Respect quiet hours.
    if in_quiet_hours(now_utc, policy):
        return ReminderDecision(False, False, "quiet_hours")

    # Cap total reminders.
    if reminder_count >= policy["max_reminders"]:
        return ReminderDecision(False, False, "max_reminders_reached")

    # Blocked students: only nudge if policy allows, and frame as offer of help.
    if progress_state == StudentProgressState.BLOCKED:
        if not policy.get("remind_blocked", True):
            return ReminderDecision(False, False, "blocked_excluded_by_policy")
        body = (
            f"You marked '{assignment_title}' as blocked. A teacher has been "
            "notified — reply here if you need anything."
        )
        escalate = reminder_count + 1 >= policy["escalate_after"]
        return ReminderDecision(True, escalate, "blocked_followup", body)

    # Silent / in-progress students get a standard nudge.
    due_phrase = ""
    if due_at:
        due_phrase = f" It is due {due_at.strftime('%Y-%m-%d %H:%M UTC')}."
    body = f"Reminder: '{assignment_title}' is still open.{due_phrase}"
    escalate = reminder_count + 1 >= policy["escalate_after"]
    reason = "silent_nudge" if progress_state == StudentProgressState.NOT_STARTED else "progress_nudge"
    return ReminderDecision(True, escalate, reason, body)
