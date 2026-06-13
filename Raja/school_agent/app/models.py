# app/models.py
import uuid
from sqlalchemy import Column, String, Boolean, ForeignKey, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship
import datetime

Base = declarative_base()

class School(Base):
    __tablename__ = "schools"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False, unique=True)

class ClassRoom(Base):
    __tablename__ = "classrooms"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    school_id = Column(String, ForeignKey("schools.id", ondelete="CASCADE"))
    name = Column(String, nullable=False) # e.g., "Grade 7-A"

class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    school_id = Column(String, ForeignKey("schools.id", ondelete="CASCADE"))
    email = Column(String, unique=True, nullable=True)
    role = Column(String, nullable=False) # "ADMIN", "TEACHER", "STUDENT", "GUARDIAN"
    name = Column(String, nullable=False)

class Assignment(Base):
    __tablename__ = "assignments"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    classroom_id = Column(String, ForeignKey("classrooms.id"))
    title = Column(String, nullable=False)
    instructions = Column(String)
    due_date = Column(DateTime, nullable=True) # Nullable for AI ambiguity workflow
    status = Column(String, default="DRAFT") # "DRAFT", "APPROVED"

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    correlation_id = Column(String, index=True, nullable=False)
    actor_id = Column(String, nullable=False)
    event_type = Column(String, nullable=False) # e.g., "ROSTER_PARSED", "ACCESS_DENIED"
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
