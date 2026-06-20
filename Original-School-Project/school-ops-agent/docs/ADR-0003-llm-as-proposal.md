# ADR-0003 — LLM as a proposal engine behind validation and human approval

- **Status:** Accepted
- **Context date:** project start

## Context

The system has to read messy documents (briefs, rosters) and free-text chat
messages and turn them into structured actions. An LLM is the right tool for the
fuzzy extraction/classification part. But LLM output is non-deterministic, can be
wrong, and — because some inputs are untrusted uploaded documents — can carry
prompt-injection attempts. The brief is explicit: "LLM output should be
structured, validated, and treated as proposed action until approved," and the
system must "protect against prompt injection inside uploaded documents" and
"separate model reasoning from deterministic business rules."

## Decision

Treat the model as a **proposal engine only**, never an actor. Concretely:

1. **One narrow interface.** `services/llm.py` exposes a single
   `structured(system, user, schema)` method that always returns JSON or raises
   `ModelError`. Callers never see free-form text.
2. **Structured + validated.** Every model output is parsed into a Pydantic
   model (`schemas/parsing.py`). Invalid output is rejected as a model failure
   and audited (`MODEL_FAILURE`); it never reaches domain tables.
3. **Provider-agnostic with a deterministic mock.** Live Anthropic/OpenAI or a
   rule-based mock, chosen by config. `auto` uses live if a key is present, else
   the mock — so the system runs offline and tests are deterministic.
4. **The model labels; deterministic code acts.** Intent classification returns a
   label; a role table (`enforce_role`) can only *downgrade* it (e.g. a student's
   message classified as `create_assignment` becomes `unknown`). Deterministic
   handlers perform the action. The model cannot escalate privilege.
5. **Injection defense in depth.** Untrusted document text is wrapped in explicit
   delimiters with a system instruction to treat it as data; a heuristic scanner
   flags override phrases; and — the real backstop — high-impact actions sit in a
   `needs_clarification` / `parsed` review state until a human approves.
6. **Ambiguity becomes a question, not a guess.** Missing/contradictory fields
   produce clarifying questions and block auto-commit (§3.2).
7. **Bounded failure.** Retries with backoff; on exhaustion a typed `ModelError`
   that callers turn into an audited failure rather than a stuck or corrupted
   record.

## Consequences

**Positive**

- A wrong or adversarial model output cannot mutate state on its own — validation
  rejects malformed output, and the approval gate stops even well-formed but
  malicious proposals.
- The mock makes the entire pipeline runnable and CI-testable with no key and no
  network, while the live path is one config flag away.
- Swapping providers (or pinning a model version) is a config change behind the
  same interface — a natural place for the bonus "feature flags for model/prompt
  versions."

**Negative / costs**

- The mock's heuristics are simpler than a live model, so offline behavior is a
  floor, not a ceiling; the evals assert the floor.
- The human-approval gate adds a step to high-impact flows. That friction is the
  point for assignment/roster creation, but we deliberately let low-impact chat
  actions (a student reporting "blocked") through without approval to keep the
  channel responsive.
- Heuristic injection scanning has false positives; we accept them because a
  false positive only routes a document to human review, which is safe.

## Notes

The separation is visible in the call graph: `intents/` and `parsers/` depend on
`services/llm.py`, but `services/assignments.py`, `services/submissions.py`, and
`scheduler/policy.py` — everything that changes state — have **no** model
dependency at all.
