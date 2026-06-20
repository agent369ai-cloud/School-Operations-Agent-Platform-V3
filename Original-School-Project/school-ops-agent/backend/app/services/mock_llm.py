"""
Deterministic mock LLM.

This is what makes the system runnable and testable with no API key. It is
NOT a toy: it implements genuine, defensible heuristics for the two model
tasks (intent classification, document field extraction) so the surrounding
pipeline — validation, ambiguity flagging, clarifying questions, approval —
is exercised exactly as it would be with a live model.

The output of every function here is a JSON string, matching what a live model
would emit, so ``LLMClient`` treats live and mock identically downstream.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

# --- Intent keyword heuristics ----------------------------------------------
_INTENT_RULES: list[tuple[str, list[str]]] = [
    ("blocked_help", ["blocked", "stuck", "can't", "cannot", "help", "don't understand",
                       "confused", "struggling"]),
    ("submission", ["submit", "submitting", "here is my", "attached", "done with",
                    "finished", "completed the", "turning in"]),
    ("resubmission", ["resubmit", "resubmitting", "revised", "updated version", "again"]),
    ("progress_update", ["progress", "halfway", "working on", "almost done",
                         "started", "in progress", "on track"]),
    ("create_assignment", ["create assignment", "new assignment", "assign", "homework due",
                           "set a task"]),
    ("cancel_assignment", ["cancel", "scrap", "remove the assignment"]),
    ("teacher_feedback", ["good work", "well done", "feedback", "needs improvement",
                          "revise", "redo"]),
    ("revision_request", ["please revise", "redo this", "revision required", "fix and resend"]),
    ("completion_decision", ["mark complete", "accepted", "approved", "looks good, complete"]),
    ("parent_opt_in", ["opt in", "opt-in", "subscribe", "yes i consent", "i agree to receive"]),
    ("parent_digest_request", ["digest", "summary of my child", "how is my child",
                               "progress report"]),
    ("escalation_acknowledgement", ["acknowledge", "received the escalation", "noted"]),
    ("roster_import", ["roster", "class list", "import students"]),
    ("policy_upload", ["policy", "quiet hours", "escalation rule"]),
    ("admin_config_change", ["change config", "update settings", "configure"]),
]

_UNSAFE_MARKERS = [
    "ignore previous instructions", "ignore all previous", "system prompt",
    "you are now", "disregard", "jailbreak", "drop table", "delete from",
]


def _classify_intent(text: str) -> tuple[str, float]:
    low = text.lower()
    # Unsafe / injection attempt -> route to unknown with high confidence.
    if any(m in low for m in _UNSAFE_MARKERS):
        return "unknown", 0.95
    best = ("unknown", 0.3)
    for intent, kws in _INTENT_RULES:
        hits = sum(1 for kw in kws if kw in low)
        if hits:
            conf = min(0.6 + 0.1 * hits, 0.95)
            if conf > best[1]:
                best = (intent, conf)
    return best


def _extract_due_date(text: str) -> str | None:
    """Find an explicit ISO-ish or 'in N days' date. Returns ISO string or None
    so the parser can flag a missing deadline as an ambiguity."""
    # ISO date
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if m:
        return f"{m.group(0)}T23:59:00+00:00"
    # "in N days"
    m = re.search(r"in (\d+) days?", text, re.I)
    if m:
        due = datetime.now(timezone.utc) + timedelta(days=int(m.group(1)))
        return due.replace(microsecond=0).isoformat()
    # Month name day
    m = re.search(r"\b(January|February|March|April|May|June|July|August|September|"
                  r"October|November|December)\s+(\d{1,2})\b", text, re.I)
    if m:
        return None  # year ambiguous -> deliberately flag for clarification
    return None


def _extract_assignment(text: str) -> dict:
    # Title: first non-empty line, trimmed.
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    title = None
    for ln in lines:
        low = ln.lower()
        m = re.match(r"(?:title|assignment|topic)\s*[:\-]\s*(.+)", ln, re.I)
        if m:
            title = m.group(1).strip()
            break
    if not title and lines:
        title = lines[0][:120]

    subject = None
    m = re.search(r"subject\s*[:\-]\s*([A-Za-z ]+)", text, re.I)
    if m:
        subject = m.group(1).strip()

    due = _extract_due_date(text)

    # Instructions: everything after a "instructions:" marker, else the body.
    instr = None
    m = re.search(r"instructions?\s*[:\-]\s*(.+)", text, re.I | re.S)
    if m:
        instr = m.group(1).strip()
    elif len(lines) > 1:
        instr = " ".join(lines[1:])[:1000]

    ambiguities = []
    questions = []
    if not due:
        ambiguities.append("No explicit due date found.")
        questions.append("What is the due date for this assignment?")
    if not subject:
        ambiguities.append("Subject not specified.")
        questions.append("Which subject is this assignment for?")
    if not title:
        ambiguities.append("Could not determine a title.")
        questions.append("What should the assignment be titled?")

    confidence = round(max(0.4, 1.0 - 0.2 * len(ambiguities)), 2)
    return {
        "title": title or "",
        "subject": subject,
        "instructions": instr or "",
        "due_at": due,
        "ambiguities": ambiguities,
        "clarifying_questions": questions,
        "confidence": confidence,
    }


def _extract_roster(text: str) -> dict:
    """Parse CSV-ish roster text into rows, flagging duplicates and missing
    guardian contact. Real CSV parsing happens in the parser; this mock path
    is used when a model is asked to interpret pasted/messy roster text."""
    rows = []
    seen = {}
    duplicates = []
    missing_contact = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw or raw.lower().startswith(("name,", "student,", "#")):
            continue
        parts = [p.strip() for p in raw.split(",")]
        name = parts[0] if parts else ""
        if not name:
            continue
        klass = parts[1] if len(parts) > 1 else None
        guardian = parts[2] if len(parts) > 2 else None
        key = name.lower()
        if key in seen:
            duplicates.append(name)
        seen[key] = True
        if not guardian:
            missing_contact.append(name)
        rows.append({"name": name, "class": klass, "guardian_contact": guardian})

    ambiguities = []
    questions = []
    if duplicates:
        ambiguities.append(f"Duplicate student rows: {', '.join(sorted(set(duplicates)))}.")
        questions.append(
            f"Row(s) for {', '.join(sorted(set(duplicates)))} appear twice — "
            "merge them or keep separate?"
        )
    if missing_contact:
        ambiguities.append(
            f"Missing guardian contact for: {', '.join(missing_contact)}."
        )
        questions.append(
            f"No guardian contact for {', '.join(missing_contact)} — proceed without?"
        )
    confidence = round(max(0.4, 1.0 - 0.15 * (len(duplicates) + len(missing_contact))), 2)
    return {
        "rows": rows,
        "ambiguities": ambiguities,
        "clarifying_questions": questions,
        "confidence": confidence,
    }


def _strip_delimiters(text: str) -> str:
    """Return only the content between the untrusted-content markers.
    The pipeline appends extraction instructions after the closing marker;
    the mock should see only the document itself, not those instructions."""
    start = "<<<UNTRUSTED_DOCUMENT_CONTENT>>>"
    end = "<<<END_UNTRUSTED_DOCUMENT_CONTENT>>>"
    s = text.find(start)
    e = text.find(end)
    if s != -1 and e != -1 and e > s:
        return text[s + len(start):e].strip()
    return text


def generate_mock(*, schema_name: str, user_text: str) -> str:
    doc_text = _strip_delimiters(user_text)
    if schema_name == "intent":
        intent, conf = _classify_intent(doc_text)
        return json.dumps({"intent": intent, "confidence": conf})
    if schema_name == "assignment_brief":
        return json.dumps(_extract_assignment(doc_text))
    if schema_name == "class_roster":
        return json.dumps(_extract_roster(doc_text))
    # Fallback: echo an empty object so callers' validation drives behavior.
    return json.dumps({})
