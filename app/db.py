import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from .config import DATABASE_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL, -- 'FACULTY' or 'STUDENT'
    phone TEXT,
    batch_id TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS timetables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    schedule_type TEXT NOT NULL,
    effective_date TEXT,
    uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS students (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE,
    phone TEXT,
    batch_id TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS faculty (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL UNIQUE,
    email TEXT UNIQUE,
    phone TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batch_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    roll_no TEXT NOT NULL,
    subject TEXT NOT NULL,
    batch TEXT NOT NULL,
    UNIQUE(roll_no, subject, batch)
);

CREATE TABLE IF NOT EXISTS teams_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch TEXT NOT NULL,
    subject TEXT NOT NULL,
    teams_url TEXT NOT NULL,
    meeting_id TEXT,
    passcode TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(batch, subject)
);

CREATE TABLE IF NOT EXISTS google_credentials (
    id INTEGER PRIMARY KEY,
    credentials_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS class_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timetable_id INTEGER,
    class_date TEXT,
    weekday TEXT,
    start_time TEXT NOT NULL,
    end_time TEXT,
    subject TEXT NOT NULL,
    batch TEXT,
    faculty_name TEXT,
    faculty_id INTEGER,
    duration_minutes INTEGER NOT NULL DEFAULT 60,
    reminder_minutes INTEGER NOT NULL DEFAULT 15,
    status TEXT NOT NULL DEFAULT 'scheduled',
    is_conducted INTEGER NOT NULL DEFAULT 0,
    teams_url TEXT,
    google_meet_space_id TEXT,
    google_meet_url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    subject_id TEXT,
    batch_id TEXT NOT NULL,
    deadline TEXT NOT NULL,
    faculty_id INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL,
    student_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    grade TEXT,
    feedback TEXT,
    UNIQUE(assignment_id, student_id),
    FOREIGN KEY(assignment_id) REFERENCES assignments(id)
);

CREATE TABLE IF NOT EXISTS assignment_reminder_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL,
    student_id TEXT NOT NULL,
    reminder_type TEXT NOT NULL, -- '24h' or '2h' or days_remaining
    sent_at TEXT NOT NULL,
    UNIQUE(assignment_id, student_id, reminder_type)
);

CREATE TABLE IF NOT EXISTS reminder_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_session_id INTEGER UNIQUE,
    assignment_id INTEGER,
    job_type TEXT DEFAULT 'class_reminder',
    send_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS delivery_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_session_id INTEGER,
    assignment_id INTEGER,
    channel TEXT, -- 'email', 'sms'
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
"""

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

@contextmanager
def connect() -> Generator[sqlite3.Connection, None, None]:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATABASE_PATH)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    finally:
        db.close()

def get_db():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATABASE_PATH)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    finally:
        db.close()

def initialize():
    with connect() as db:
        db.executescript(SCHEMA)
        try:
            columns = [row[1] for row in db.execute("PRAGMA table_info(class_sessions)").fetchall()]
            if "google_meet_space_id" not in columns:
                db.execute("ALTER TABLE class_sessions ADD COLUMN google_meet_space_id TEXT")
            if "google_meet_url" not in columns:
                db.execute("ALTER TABLE class_sessions ADD COLUMN google_meet_url TEXT")
        except Exception:
            pass
