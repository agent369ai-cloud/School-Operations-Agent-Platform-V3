from app.database import SessionLocal
from app.models import School, ClassRoom, User

def inspect_database():
    db = SessionLocal()
    try:
        print("=" * 60)
        print("📋 REGISTERED SCHOOLS & PROVISIONED CLASSROOMS")
        print("=" * 60)
        
        # 1. Fetch all registered schools
        schools = db.query(School).all()
        
        if not schools:
            print("❌ No schools found. Please run 'python seed.py' first.")
            return

        for school in schools:
            print(f"\n🏫 School Name: {school.name}")
            print(f"🆔 School UUID: {school.id}")
            
            # 2. Query classrooms assigned specifically to this school's ID
            classrooms = db.query(ClassRoom).filter(ClassRoom.school_id == school.id).all()
            print("🧱 Active Classrooms/Grades:")
            if classrooms:
                for idx, room in enumerate(classrooms, start=1):
                    print(f"  {idx}. {room.name} (Room ID: {room.id})")
            else:
                print("  ⚠️ No classrooms provisioned for this school.")
                
            # 3. Query the designated system admin for this school
            admin = db.query(User).filter(User.school_id == school.id, User.role == "ADMIN").first()
            if admin:
                print(f"👤 Assigned Administrator: {admin.name} ({admin.email})")
            else:
                print("  ⚠️ No admin user linked to this school.")
                
        print("\n" + "=" * 60)
        
    except Exception as e:
        print(f"❌ Diagnostic Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    inspect_database()
