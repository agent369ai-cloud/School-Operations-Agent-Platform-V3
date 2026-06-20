"""
Authorization & policy tests.

These exercise the rubric's "Auth and Authorization" + "wrong-context handling"
expectations end to end through the HTTP layer, plus direct unit tests of the
pure policy engine.
"""
from __future__ import annotations

import uuid

import pytest

from app.core.authz import (
    AccessDenied,
    AuthContext,
    require_teacher_of_class,
    require_same_school,
)
from app.models.enums import Role
from tests.conftest import auth_header


# --- Pure policy-engine unit tests ------------------------------------------
def test_cross_school_denied():
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    ctx = AuthContext(uuid.uuid4(), s1, Role.ADMIN)
    with pytest.raises(AccessDenied) as e:
        require_same_school(ctx, s2)
    assert e.value.reason == "cross_school_access"


def test_teacher_unassigned_class_denied():
    school = uuid.uuid4()
    c1, c2 = uuid.uuid4(), uuid.uuid4()
    teacher = AuthContext(uuid.uuid4(), school, Role.TEACHER, frozenset({c1}))
    require_teacher_of_class(teacher, resource_school_id=school, class_id=c1)  # ok
    with pytest.raises(AccessDenied) as e:
        require_teacher_of_class(teacher, resource_school_id=school, class_id=c2)
    assert e.value.reason == "teacher_not_assigned_to_class"


def test_admin_bypasses_class_scope_within_school():
    school = uuid.uuid4()
    admin = AuthContext(uuid.uuid4(), school, Role.ADMIN)
    # No raise.
    require_teacher_of_class(admin, resource_school_id=school, class_id=uuid.uuid4())


# --- HTTP-level tests --------------------------------------------------------
def test_unauthenticated_rejected(client):
    assert client.get("/api/dashboard/admin").status_code == 401


def test_two_schools_are_isolated(client):
    a = client.post("/api/auth/register", json={
        "school_name": "School A", "admin_name": "A", "admin_email": "a@a.edu",
        "admin_password": "Password123!"}).json()
    b = client.post("/api/auth/register", json={
        "school_name": "School B", "admin_name": "B", "admin_email": "b@b.edu",
        "admin_password": "Password123!"}).json()

    # Admin A creates a class.
    ca = client.post("/api/admin/classes", json={"name": "A-1"},
                     headers=auth_header(a["access_token"]))
    assert ca.status_code == 201
    class_a_id = ca.json()["id"]

    # Admin B must not see School A's classes.
    listing = client.get("/api/admin/classes",
                         headers=auth_header(b["access_token"])).json()
    assert all(c["id"] != class_a_id for c in listing)

    # Admin B cannot assign a teacher to School A's class (404, not found in B).
    # First create a teacher invite/accept in B.
    inv = client.post("/api/auth/invites",
                      json={"role": "teacher", "email": "t@b.edu"},
                      headers=auth_header(b["access_token"])).json()
    tok = client.post("/api/auth/invites/accept", json={
        "token": inv["token"], "full_name": "T B", "password": "Password123!"
    }).json()
    resp = client.post("/api/admin/teacher-assignments",
                       json={"teacher_id": tok["user_id"], "class_id": class_a_id},
                       headers=auth_header(b["access_token"]))
    assert resp.status_code == 404


def test_teacher_cannot_create_assignment_in_unassigned_class(client):
    admin = client.post("/api/auth/register", json={
        "school_name": "S", "admin_name": "A", "admin_email": "a@s.edu",
        "admin_password": "Password123!"}).json()
    ah = auth_header(admin["access_token"])
    c1 = client.post("/api/admin/classes", json={"name": "C1"}, headers=ah).json()
    c2 = client.post("/api/admin/classes", json={"name": "C2"}, headers=ah).json()

    inv = client.post("/api/auth/invites",
                      json={"role": "teacher", "email": "t@s.edu", "class_id": c1["id"]},
                      headers=ah).json()
    teacher = client.post("/api/auth/invites/accept", json={
        "token": inv["token"], "full_name": "T", "password": "Password123!"}).json()
    th = auth_header(teacher["access_token"])

    # Allowed in assigned class c1.
    ok = client.post("/api/assignments",
                     json={"title": "HW1", "class_id": c1["id"]}, headers=th)
    assert ok.status_code == 201

    # Denied in unassigned class c2 -> 403 + audited.
    denied = client.post("/api/assignments",
                         json={"title": "HW2", "class_id": c2["id"]}, headers=th)
    assert denied.status_code == 403

    # The denial appears in the admin's audit timeline.
    audit = client.get("/api/audit", headers=ah).json()
    assert any(e["event_type"] == "access_denied" for e in audit)


def test_student_cannot_invite_teacher(client):
    admin = client.post("/api/auth/register", json={
        "school_name": "S", "admin_name": "A", "admin_email": "a@s.edu",
        "admin_password": "Password123!"}).json()
    ah = auth_header(admin["access_token"])
    inv = client.post("/api/auth/invites",
                      json={"role": "student"}, headers=ah).json()
    student = client.post("/api/auth/invites/accept", json={
        "token": inv["token"], "full_name": "Stu"}).json()
    sh = auth_header(student["access_token"])
    # Student attempts to invite a teacher.
    resp = client.post("/api/auth/invites", json={"role": "teacher"}, headers=sh)
    assert resp.status_code == 403
