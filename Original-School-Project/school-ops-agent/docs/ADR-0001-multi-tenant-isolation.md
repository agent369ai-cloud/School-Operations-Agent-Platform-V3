# ADR-0001 — Multi-tenant isolation via denormalized `school_id` + a fail-closed policy engine

- **Status:** Accepted
- **Context date:** project start

## Context

The platform is multi-tenant: many schools share one deployment, and the single
most damaging failure would be one school seeing or mutating another school's
data (or a teacher acting on a class they're not assigned to). The brief calls
this out explicitly — every actor has an access boundary, and the system must
"prevent obvious cross-school or cross-class mistakes."

We need an isolation approach that is (a) hard to get wrong, (b) cheap to check
on every request, and (c) simple enough that a junior engineer can read the
entire access-control surface and extend it safely.

## Options considered

1. **Row-level security in the database (Postgres RLS).** Strong, but ties us to
   Postgres (we want SQLite for zero-setup local/demo/test), pushes policy into
   SQL where it's hard to unit test, and is easy to misconfigure silently.
2. **Tenancy inferred by joining up to the owning school each check.** Normalized
   and DRY, but every authorization check becomes a multi-table join, which is
   both slower and easier to get subtly wrong as the schema grows.
3. **Denormalize `school_id` onto every tenant-scoped row + a small pure-Python
   policy engine.** Each row self-identifies its tenant; the policy engine
   compares the actor's school to the resource's school before anything else.

## Decision

We chose **option 3**.

- Every tenant-scoped table carries a `school_id` foreign key, even when it could
  be derived (e.g. a submission carries both `assignment_id` and `school_id`).
- A single module, `app/core/authz.py`, holds the entire policy: tenancy checks,
  role gates, and class/student-scoped checks. It operates on a small
  `AuthContext` value object (no ORM, no framework imports) so it is trivially
  unit-testable.
- The order is always **tenancy first, then role, then resource scope**, and the
  default is **deny** (unknown combinations raise `AccessDenied`).
- Denials are audited (`ACCESS_DENIED`), so wrong-context attempts are visible in
  the timeline rather than silent.

## Consequences

**Positive**

- Authorization checks are O(1) field comparisons, no joins.
- The database still enforces referential integrity, so a row physically cannot
  reference a resource in another school.
- The policy is one readable file with direct unit tests (see
  `tests/test_authz.py`), which is exactly what a junior needs to extend it.
- Works identically on SQLite and Postgres.

**Negative / costs**

- Mild denormalization: `school_id` is duplicated onto child rows. If a row could
  ever be re-parented to a different school we'd have to update it — but in this
  domain resources never move between schools, so the duplication is safe.
- Application-layer enforcement means a raw SQL client bypassing the app would
  bypass the policy. For this exercise the app is the only writer; in production
  I'd add Postgres RLS as defense in depth behind the same `school_id` columns.

## Notes

The denormalized column is what makes option-3 cheap; without it this would
collapse into option 2. The fail-closed default is the other half — a new
resource type with no rule is inaccessible until someone writes its rule, which
is the safe direction to fail.
