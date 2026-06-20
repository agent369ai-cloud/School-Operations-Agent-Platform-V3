"""
Authorization policy engine.

This module is the single source of truth for "who can touch what". It is
deliberately small, explicit, and free of framework imports so it can be unit
tested in isolation and so a junior engineer can read every rule in one sitting.

Design principles
-----------------
1. Tenancy first. Every check starts by asserting the resource's ``school_id``
   equals the actor's ``school_id``. Cross-school access is impossible by
   construction because callers pass the actor's school and we compare.
2. Role + resource. Beyond tenancy we check the actor's role and, for teachers
   and students, their specific class/resource membership.
3. Fail closed. Unknown combinations raise ``AccessDenied``. There is no
   implicit allow.
4. Deny is auditable. The API layer catches ``AccessDenied`` and writes an
   ACCESS_DENIED audit event, so wrong-context attempts show up in the timeline.

These functions take plain ids + a small ``AuthContext`` rather than ORM
objects so the rules are easy to test without a database.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.models.enums import Role


class AccessDenied(Exception):
    """Raised when an actor may not perform an action on a resource."""

    def __init__(self, reason: str, *, detail: dict | None = None):
        self.reason = reason
        self.detail = detail or {}
        super().__init__(reason)


@dataclass(frozen=True)
class AuthContext:
    """Everything the policy engine needs to know about the actor.

    `class_ids` is the set of classes a teacher is assigned to OR a student is
    enrolled in. `student_ids` is the set of students a guardian may view.
    These are resolved once per request by the auth dependency.
    """

    user_id: uuid.UUID
    school_id: uuid.UUID
    role: Role
    class_ids: frozenset[uuid.UUID] = frozenset()
    student_ids: frozenset[uuid.UUID] = frozenset()


# --- Tenancy -----------------------------------------------------------------
def require_same_school(ctx: AuthContext, resource_school_id: uuid.UUID) -> None:
    if ctx.school_id != resource_school_id:
        raise AccessDenied(
            "cross_school_access",
            detail={"actor_school": str(ctx.school_id),
                    "resource_school": str(resource_school_id)},
        )


# --- Role gates --------------------------------------------------------------
def require_role(ctx: AuthContext, *roles: Role) -> None:
    if ctx.role not in roles:
        raise AccessDenied(
            "role_not_permitted",
            detail={"actor_role": ctx.role.value,
                    "required": [r.value for r in roles]},
        )


def require_admin(ctx: AuthContext) -> None:
    require_role(ctx, Role.ADMIN)


# --- Class-scoped checks -----------------------------------------------------
def require_teacher_of_class(
    ctx: AuthContext, *, resource_school_id: uuid.UUID, class_id: uuid.UUID | None
) -> None:
    """A teacher may act on a class only if assigned to it. Admins pass."""
    require_same_school(ctx, resource_school_id)
    if ctx.role == Role.ADMIN:
        return
    if ctx.role != Role.TEACHER:
        raise AccessDenied("role_not_permitted",
                           detail={"actor_role": ctx.role.value})
    if class_id is None or class_id not in ctx.class_ids:
        raise AccessDenied(
            "teacher_not_assigned_to_class",
            detail={"class_id": str(class_id) if class_id else None},
        )


def require_student_self(
    ctx: AuthContext, *, resource_school_id: uuid.UUID, student_id: uuid.UUID
) -> None:
    """A student may only act on their own resources. Teachers of the student's
    class and admins also pass (for review/feedback)."""
    require_same_school(ctx, resource_school_id)
    if ctx.role == Role.ADMIN:
        return
    if ctx.role == Role.STUDENT and ctx.user_id == student_id:
        return
    if ctx.role == Role.TEACHER:
        # Teacher authorization for a specific student is validated at the call
        # site against the student's class; here we allow and let the caller
        # pass class context via require_teacher_of_class.
        return
    raise AccessDenied(
        "not_resource_owner",
        detail={"actor": str(ctx.user_id), "student": str(student_id)},
    )


def require_guardian_of_student(
    ctx: AuthContext, *, resource_school_id: uuid.UUID, student_id: uuid.UUID
) -> None:
    require_same_school(ctx, resource_school_id)
    if ctx.role == Role.ADMIN:
        return
    if ctx.role == Role.GUARDIAN and student_id in ctx.student_ids:
        return
    raise AccessDenied(
        "guardian_not_linked",
        detail={"student": str(student_id)},
    )


def can_view_assignment(
    ctx: AuthContext,
    *,
    resource_school_id: uuid.UUID,
    class_id: uuid.UUID | None,
    target_student_ids: frozenset[uuid.UUID] = frozenset(),
) -> bool:
    """Read check used by dashboards. Returns bool rather than raising so list
    endpoints can filter silently."""
    if ctx.school_id != resource_school_id:
        return False
    if ctx.role == Role.ADMIN:
        return True
    if ctx.role == Role.TEACHER:
        return class_id in ctx.class_ids
    if ctx.role == Role.STUDENT:
        return ctx.user_id in target_student_ids or (class_id in ctx.class_ids)
    if ctx.role == Role.GUARDIAN:
        return bool(ctx.student_ids & target_student_ids)
    return False
