# ADR-0002 — Lifecycle state machines as data, validated in services

- **Status:** Accepted
- **Context date:** project start

## Context

Assignments and submissions have real lifecycles. The brief asks for "explicit
and defensible" state transitions and for a design where "retries, duplicates,
wrong-context actions, and model failures do not corrupt state." The risk we're
guarding against is an invalid transition — e.g. a submission jumping straight
from `submitted` to `completed` without review, or an assignment going `draft →
active` while skipping `published` and never materializing student targets.

## Options considered

1. **Implicit transitions in handlers.** Each endpoint sets the next status with
   ad-hoc `if` checks. Fast to write, but the rules are scattered, easy to
   contradict between endpoints, and impossible to see as a whole.
2. **A workflow/state-machine library.** Powerful, but heavy for two small
   lifecycles and adds a dependency a junior must learn before touching status.
3. **Declare the legal transitions as data + a single assert function, called
   from service functions.** The whole lifecycle is one readable map; every
   mutation goes through one validated path.

## Decision

We chose **option 3**.

- `models/enums.py` declares `ASSIGNMENT_TRANSITIONS` and
  `SUBMISSION_TRANSITIONS` as explicit `{state: {allowed next states}}` maps,
  plus `assert_*_transition` helpers that raise `StateTransitionError` on an
  illegal move.
- All status changes happen inside service functions
  (`services/assignments.py`, `services/submissions.py`), never directly in route
  handlers. The service validates the transition, performs side effects (e.g.
  materializing `AssignmentTarget` rows on publish), and writes an audit event.
- `StateTransitionError` maps to HTTP 409 at the API edge.

## Consequences

**Positive**

- The complete lifecycle is visible in one place and unit-testable without a
  database (see `tests/test_scenario.py`): legal paths pass, illegal jumps raise,
  terminal states are terminal.
- Because every transition flows through one function, the audit event and any
  side effect (target materialization, progress-row updates) can't be forgotten.
- Adding a state or an edge is a one-line change to the map — a safe junior task,
  which is exactly the kind of extension the interview's pairing round asks for.

**Negative / costs**

- The maps and the service layer are slightly more ceremony than inline `if`s for
  a two-state toy. The payoff is correctness and legibility as states multiply.
- Transitions are enforced in the application, not by a DB constraint. A check
  constraint can't express "submitted → under_review is allowed but submitted →
  completed is not," so the service layer is the right place; we accept that a
  raw SQL writer could bypass it (the app is the only writer here).

## Notes

The resubmission loop (`revision_required → submitted`) is deliberately a legal
edge so a student can iterate, while `completed` is terminal. The attempt counter
on `Submission` increments on each resubmit, giving an auditable history of tries
without mutating prior rows.
