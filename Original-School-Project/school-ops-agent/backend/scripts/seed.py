"""
Seed the demo scenario described in the assignment's "Minimum Live Scenario".

Creates:
  * School "Lincoln High" + admin (admin@lincoln.test / Password123!)
  * Two classes: Grade 7-A, Grade 8-B
  * One teacher (teacher@lincoln.test / Password123!) assigned to 7-A
  * Two students enrolled in 7-A, with verified mock chat identities
  * One guardian linked to the first student

Run:  python -m scripts.seed
"""
from __future__ import annotations

from app.core.security import hash_password
from app.db.base import SessionLocal, init_db
from app.models.core import (
    ChatIdentity,
    Enrollment,
    GuardianStudentLink,
    School,
    SchoolClass,
    TeacherClassLink,
    User,
)
from app.models.enums import Role

ADMIN_PW = "Password123!"


def run() -> None:
    init_db()
    db = SessionLocal()
    try:
        if db.query(School).filter(School.name == "Lincoln High").first():
            print("Already seeded.")
            return

        school = School(
            name="Lincoln High",
            policy={
                "quiet_hours": {"start": 21, "end": 7},
                "timezone_offset_minutes": 0,
                "max_reminders": 3,
                "escalate_after": 2,
                "remind_blocked": True,
                "allowed_channels": ["telegram"],
            },
        )
        db.add(school)
        db.flush()

        admin = User(school_id=school.id, role=Role.ADMIN, email="admin@lincoln.test",
                     full_name="Ada Admin", hashed_password=hash_password(ADMIN_PW))
        teacher = User(school_id=school.id, role=Role.TEACHER, email="teacher@lincoln.test",
                       full_name="Tom Teacher", hashed_password=hash_password(ADMIN_PW))
        db.add_all([admin, teacher])
        db.flush()

        c7 = SchoolClass(school_id=school.id, name="Grade 7-A", grade_level="7")
        c8 = SchoolClass(school_id=school.id, name="Grade 8-B", grade_level="8")
        db.add_all([c7, c8])
        db.flush()

        db.add(TeacherClassLink(school_id=school.id, teacher_id=teacher.id, class_id=c7.id))

        s1 = User(school_id=school.id, role=Role.STUDENT, full_name="Sara Student",
                  email="sara@lincoln.test", hashed_password=hash_password(ADMIN_PW))
        s2 = User(school_id=school.id, role=Role.STUDENT, full_name="Sam Student",
                  email="sam@lincoln.test", hashed_password=hash_password(ADMIN_PW))
        guardian = User(school_id=school.id, role=Role.GUARDIAN, full_name="Gita Guardian",
                        email="guardian@lincoln.test", hashed_password=hash_password(ADMIN_PW))
        db.add_all([s1, s2, guardian])
        db.flush()

        db.add_all([
            Enrollment(school_id=school.id, student_id=s1.id, class_id=c7.id),
            Enrollment(school_id=school.id, student_id=s2.id, class_id=c7.id),
            GuardianStudentLink(school_id=school.id, guardian_id=guardian.id,
                                student_id=s1.id, opted_in=True),
            # Verified mock chat identities so the chat demo works immediately.
            ChatIdentity(school_id=school.id, user_id=s1.id, channel="telegram",
                         external_id="tg_sara", verified=True),
            ChatIdentity(school_id=school.id, user_id=s2.id, channel="telegram",
                         external_id="tg_sam", verified=True),
            ChatIdentity(school_id=school.id, user_id=guardian.id, channel="telegram",
                         external_id="tg_gita", verified=True),
        ])
        db.commit()

        print("Seed complete.")
        print(f"  School:   {school.name} ({school.id})")
        print(f"  Admin:    admin@lincoln.test / {ADMIN_PW}")
        print(f"  Teacher:  teacher@lincoln.test / {ADMIN_PW}")
        print(f"  Student:  sara@lincoln.test / {ADMIN_PW}  (Sara, {s1.id}, tg_sara)")
        print(f"  Student:  sam@lincoln.test / {ADMIN_PW}   (Sam, {s2.id}, tg_sam)")
        print(f"  Guardian: guardian@lincoln.test / {ADMIN_PW}  (Gita, {guardian.id}, tg_gita -> Sara)")
        print(f"  Classes:  Grade 7-A ({c7.id}), Grade 8-B ({c8.id})")
    finally:
        db.close()


if __name__ == "__main__":
    run()
