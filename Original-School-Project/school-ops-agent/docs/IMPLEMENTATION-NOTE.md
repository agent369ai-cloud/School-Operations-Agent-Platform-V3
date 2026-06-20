# Implementation Note

**Assumptions.** One deployment serves many schools; a school is the tenant root
and the first admin bootstraps it. Students and guardians authenticate through a
linked chat identity rather than web passwords, so their `User` rows allow a null
password. Telegram is the primary channel; a WhatsApp adapter is included (mock)
to prove the canonical envelope generalizes. I optimized for a correct,
defensible slice over breadth, per the ground rules.

**Domain & access model.** Entities: school, class, user (role-discriminated:
admin/teacher/student/guardian), teacher–class (M2M), enrollment, guardian–student
link, chat identity, invite, document, assignment, per-student assignment target,
submission, feedback, reminder, inbound message, idempotency key, and an
append-only audit event. Every tenant-scoped row carries `school_id` so the
authorization engine establishes tenancy with a field comparison, not a join. A
small pure-Python policy engine enforces tenancy → role → resource scope, fails
closed, and audits every denial. Class-targeted assignments materialize one
target row per enrolled student at publish time so progress and reminders have
concrete state to track.

**Parsing strategy.** extract → injection-guard → model structured output →
Pydantic validation → review state → human approval → commit. Untrusted document
text is wrapped in delimiters and the model is told to treat it as data; a
heuristic scanner forces ambiguous or injection-flagged documents into review.
Missing fields (a brief with no due date, a roster with a duplicate row or
missing guardian contact) become explicit clarifying questions instead of
silent guesses. The original bytes, parsed output, confidence, ambiguity notes,
and approval state are all persisted. Two document types are fully wired (brief,
roster); approval drives the side effect (roster import creates students +
enrollments). An LLM client abstracts Anthropic/OpenAI with a deterministic mock
fallback so the whole pipeline runs offline and deterministically in CI.

**Intent layer.** Chat messages and documents route through a classifier that
covers all required intents plus unknown/unsafe. The model only *labels*; a role
table can downgrade a disallowed intent to unknown, so misclassification can't
escalate privilege. Deterministic handlers perform the action — the model never
acts directly.

**State model.** Assignment (draft→published→active→archived, with cancel) and
submission (submitted→under_review→revision_required→submitted→…→completed)
lifecycles are declared as transition maps and validated in services; illegal
transitions return 409. Resubmission increments an attempt counter; completed and
cancelled/archived are terminal.

**Failures handled.** Webhook retries dedupe on (channel, provider_message_id);
double form submits honor an Idempotency-Key; repeated uploads dedupe on content
hash; reminders are unique per (target, dedup window) so a sweep that re-runs or
resumes after a crash never double-sends. The scheduler keeps all state in the
database, so restart resumes cleanly and nothing is stuck silently. Model/API
failures raise a typed error that is audited as a model failure rather than
corrupting state. Access denials, model failures, and every important action are
written to the audit log, which powers a timeline and a live SSE ribbon so a
wrong reminder or bad parse is debuggable without touching the database. Logs are
structured JSON with a correlation id threaded from middleware and the chat
dispatcher through the whole flow.

**Security & privacy.** No secrets in git (`.env.example` + rotation notes),
upload extension/size validation, server-generated storage filenames, JWT expiry
and route protection, configurable CORS, a basic rate limiter, and PII screening
of audit detail so dashboards don't leak student/guardian data.

**What I'd improve next.** (1) Replace the in-process SSE event bus with Redis
pub/sub behind the same interface for multi-instance fan-out. (2) Move document
parsing to a background worker so large files don't block the upload request. (3)
Adopt Alembic migrations for the Postgres path instead of create_all. (4) Add an
output-side validator that cross-checks model-extracted field values against the
source text to further blunt injection. (5) Harden uploads with malware/bomb
scanning and isolate the parser. (6) Add Postgres row-level security as defense
in depth behind the existing school_id columns. (7) Flesh out group-target
membership, which is modeled but currently resolves like a class.
