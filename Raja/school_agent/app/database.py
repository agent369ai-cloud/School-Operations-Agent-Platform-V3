from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import Base

# For rapid development, we use SQLite local file.
# Change this string to your Neon/Supabase Postgres URL later if needed.
DATABASE_URL = "sqlite:///./school.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
