"""SQLAlchemy Models for Openclass."""

from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    ForeignKey,
    DateTime,
    Boolean,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from .config import DATABASE_PATH

Base = declarative_base()
engine = create_engine(f"sqlite:///{DATABASE_PATH}", echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_sa_session():
    """SQLAlchemy Session generator for FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)  # 'FACULTY' or 'STUDENT'
    password_hash = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    batch_id = Column(String, nullable=True)
    active = Column(Integer, default=1, nullable=False)
    created_at = Column(String, default=utc_now_iso, nullable=False)
    updated_at = Column(String, default=utc_now_iso, nullable=False)


class Student(Base):
    __tablename__ = "students"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=True, index=True)
    phone = Column(String, nullable=True)
    batch_id = Column(String, nullable=True)
    batch = Column(String, nullable=True)
    stamp = Column(String, nullable=True)
    active = Column(Integer, default=1, nullable=False)
    updated_at = Column(String, default=utc_now_iso, nullable=False)


class Faculty(Base):
    __tablename__ = "faculty"

    id = Column(Integer, primary_key=True, autoincrement=True)
    full_name = Column(String, unique=True, nullable=False)
    email = Column(String, unique=True, nullable=True, index=True)
    phone = Column(String, nullable=True)
    active = Column(Integer, default=1, nullable=False)
    updated_at = Column(String, default=utc_now_iso, nullable=False)


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    subject = Column(String, nullable=True)
    subject_id = Column(String, nullable=True)
    batch_id = Column(String, nullable=False, index=True)
    deadline = Column(String, nullable=False)  # ISO timestamp
    faculty_id = Column(Integer, nullable=True)
    faculty_name = Column(String, nullable=True)  # Faculty Creator
    created_at = Column(String, default=utc_now_iso, nullable=False)
    updated_at = Column(String, default=utc_now_iso, nullable=False)

    submissions = relationship("Submission", back_populates="assignment", cascade="all, delete-orphan")


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), nullable=False, index=True)
    student_id = Column(String, nullable=False, index=True)
    student_name = Column(String, nullable=True)
    file_path = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    submitted_at = Column(String, default=utc_now_iso, nullable=False)
    grade = Column(String, nullable=True)
    feedback = Column(Text, nullable=True)

    assignment = relationship("Assignment", back_populates="submissions")


class ClassSession(Base):
    __tablename__ = "class_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timetable_id = Column(Integer, nullable=True)
    class_date = Column(String, nullable=True)
    weekday = Column(String, nullable=True)
    start_time = Column(String, nullable=False)
    end_time = Column(String, nullable=True)
    subject = Column(String, nullable=False)
    batch = Column(String, nullable=True)
    faculty_name = Column(String, nullable=True)
    faculty_id = Column(Integer, nullable=True)
    duration_minutes = Column(Integer, default=60, nullable=False)
    reminder_minutes = Column(Integer, default=15, nullable=False)
    status = Column(String, default="scheduled", nullable=False)
    is_conducted = Column(Integer, default=0, nullable=False)
    google_meet_space_id = Column(String, nullable=True)
    google_meet_url = Column(String, nullable=True)
    created_at = Column(String, default=utc_now_iso, nullable=False)
    updated_at = Column(String, default=utc_now_iso, nullable=False)


class AssignmentReminderLog(Base):
    __tablename__ = "assignment_reminder_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    assignment_id = Column(Integer, nullable=False, index=True)
    student_id = Column(String, nullable=False)
    reminder_type = Column(String, nullable=False)
    sent_at = Column(String, default=utc_now_iso, nullable=False)


class DeliveryLog(Base):
    __tablename__ = "delivery_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    class_session_id = Column(Integer, nullable=True)
    assignment_id = Column(Integer, nullable=True)
    channel = Column(String, nullable=True)  # 'email', 'sms'
    action = Column(String, nullable=False)
    status = Column(String, nullable=False)
    detail = Column(Text, nullable=True)
    created_at = Column(String, default=utc_now_iso, nullable=False)
