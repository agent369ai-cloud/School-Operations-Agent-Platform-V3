import uuid
from app.database import SessionLocal, init_db
from app.models import School, ClassRoom, User

def seed_demo_data():
    print("Initializing demo database tables...")
    init_db()
    
    db = SessionLocal()
    try:
        # --- 1. LINCOLN HIGH SETUP ---
        lincoln_school = db.query(School).filter(School.name == "Lincoln High").first()
        if not lincoln_school:
            print("Seeding Step 1: Registering 'Lincoln High'...")
            lincoln_school = School(name="Lincoln High")
            db.add(lincoln_school)
            db.flush()

            print("Seeding Step 2: Provisioning Lincoln High classrooms...")
            class_7a = ClassRoom(school_id=lincoln_school.id, name="Grade 7-A")
            class_8b = ClassRoom(school_id=lincoln_school.id, name="Grade 8-B")
            class_8c = ClassRoom(school_id=lincoln_school.id, name="Grade 8-C")
            db.add_all([class_7a, class_8b, class_8c])

            print("Seeding Step 3: Generating Lincoln High Admin profile...")
            admin = User(
                school_id=lincoln_school.id,
                email="admin@lincolnhigh.edu",
                name="Principal Reynolds",
                role="ADMIN"
            )
            db.add(admin)
            db.flush()

        # --- 2. OXFORD ACADEMY SETUP ---
        oxford_school = db.query(School).filter(School.name == "Oxford Academy").first()
        if not oxford_school:
            print("Seeding Step 4: Registering 'Oxford Academy'...")
            oxford_school = School(name="Oxford Academy")
            db.add(oxford_school)
            db.flush()

            print("Seeding Step 5: Provisioning Oxford Academy classrooms...")
            oxford_7a = ClassRoom(school_id=oxford_school.id, name="Oxford Grade 7-A")
            oxford_8b = ClassRoom(school_id=oxford_school.id, name="Oxford Grade 8-B")
            db.add_all([oxford_7a, oxford_8b])

            print("Seeding Step 6: Generating Oxford Academy Admin profile...")
            oxford_admin = User(
                school_id=oxford_school.id,
                email="admin@oxford.edu",
                name="Principal Higgins",
                role="ADMIN"
            )
            db.add(oxford_admin)

        db.commit()
        print("Successfully seeded all schools and classrooms!")
        
    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed_demo_data()
