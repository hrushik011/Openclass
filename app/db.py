import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Generator

from .config import DATABASE_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL, -- 'FACULTY' or 'STUDENT'
    password_hash TEXT,
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
    google_meet_space_id TEXT,
    google_meet_url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    subject TEXT,
    subject_id TEXT,
    batch_id TEXT NOT NULL,
    deadline TEXT NOT NULL,
    faculty_id INTEGER,
    faculty_name TEXT,
    reference_file_path TEXT,
    reference_filename TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL,
    student_id TEXT NOT NULL,
    student_name TEXT,
    file_path TEXT NOT NULL,
    original_filename TEXT NOT NULL DEFAULT 'submission.pdf',
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
    reminder_type TEXT NOT NULL, -- '24h', '2h', or '3d'
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

CREATE TABLE IF NOT EXISTS lecture_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    subject TEXT NOT NULL,
    specialization TEXT,
    file_path TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    faculty_name TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attendance_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    student_name TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    class_id INTEGER NOT NULL,
    subject TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Present', -- 'Present', 'Absent', or 'Late'
    timestamp TEXT NOT NULL,
    verified_by_faculty INTEGER NOT NULL DEFAULT 0,
    UNIQUE(student_id, class_id)
);

CREATE TABLE IF NOT EXISTS attendance_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    student_name TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    class_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Absent',
    timestamp TEXT,
    verified_by_faculty BOOLEAN DEFAULT 0
);

CREATE TABLE IF NOT EXISTS threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT,
    scope_type TEXT NOT NULL DEFAULT 'public',
    batch_id TEXT,
    subject TEXT,
    recipient_faculty_id INTEGER,
    author_id TEXT,
    author_name TEXT,
    author_role TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS thread_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL,
    author_id TEXT,
    author_name TEXT,
    author_role TEXT,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(thread_id) REFERENCES threads(id)
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

def _add_column_if_missing(db: sqlite3.Connection, table: str, column: str, col_type: str):
    try:
        columns = [row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except Exception:
        pass

def seed_default_data(db: sqlite3.Connection):
    """Seed initial faculty, students, classes, and assignments if not present."""
    stamp = now()
    
    # 1. Faculty
    faculty_data = [
        ("Priya Menon", "priya.menon@college.edu", "+919876543210"),
        ("Professor Iyer", "iyer@college.edu", "+919876543211"),
        ("Dr. Nandita Bose", "bose@college.edu", "+919876543212"),
    ]
    for full_name, email, phone in faculty_data:
        db.execute(
            """INSERT INTO faculty (full_name, email, phone, active, updated_at)
               VALUES (?, ?, ?, 1, ?)
               ON CONFLICT(full_name) DO UPDATE SET email=excluded.email, phone=excluded.phone""",
            (full_name, email, phone, stamp)
        )
        db.execute(
            """INSERT INTO users (email, name, role, phone, active, created_at, updated_at)
               VALUES (?, ?, 'FACULTY', ?, 1, ?, ?)
               ON CONFLICT(email) DO UPDATE SET name=excluded.name, role='FACULTY'""",
            (email, full_name, phone, stamp, stamp)
        )

    # 2. Students
    students_data = [
        ("std-001", "Arjun Rao", "arjun.rao@college.edu", "+919876543220", "CS-2A"),
        ("std-002", "Meera Shah", "meera.shah@college.edu", "+919876543221", "CS-2A"),
        ("std-003", "Karan Verma", "karan.verma@college.edu", "+919876543222", "CS-2A"),
        ("std-004", "Ananya Iyer", "ananya.iyer@college.edu", "+919876543223", "CS-2A"),
        ("std-005", "Rohan Varma", "rohan.varma@college.edu", "+919876543224", "CS-1B"),
        ("std-006", "Sneha Kapoor", "sneha.kapoor@college.edu", "+919876543225", "CS-1B"),
    ]
    for sid, name, email, phone, batch in students_data:
        db.execute(
            """INSERT INTO students (id, name, email, phone, batch_id, active, updated_at)
               VALUES (?, ?, ?, ?, ?, 1, ?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, email=excluded.email, batch_id=excluded.batch_id""",
            (sid, name, email, phone, batch, stamp)
        )
        db.execute(
            """INSERT INTO users (email, name, role, phone, batch_id, active, created_at, updated_at)
               VALUES (?, ?, 'STUDENT', ?, ?, 1, ?, ?)
               ON CONFLICT(email) DO UPDATE SET name=excluded.name, role='STUDENT', batch_id=excluded.batch_id""",
            (email, name, phone, batch, stamp, stamp)
        )
        # Also batch allocation
        db.execute(
            """INSERT OR IGNORE INTO batch_allocations (roll_no, subject, batch)
               VALUES (?, 'Data Structures', ?)""",
            (sid, batch)
        )

    # 3. Seed initial upcoming class sessions if empty
    session_count = db.execute("SELECT count(*) FROM class_sessions").fetchone()[0]
    if session_count == 0:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        db.execute(
            """INSERT INTO class_sessions (
                class_date, weekday, start_time, end_time, subject, batch,
                faculty_name, faculty_id, duration_minutes, reminder_minutes, status,
                google_meet_space_id, google_meet_url, created_at, updated_at
            ) VALUES (
                ?, 'Thursday', '10:00', '11:00', 'Data Structures CS-2A', 'CS-2A',
                'Professor Iyer', 2, 60, 15, 'scheduled',
                'spaces/ds-cs2a-lecture08', 'https://meet.google.com/dks-pqnr-kty', ?, ?
            )""",
            (today_str, stamp, stamp)
        )
        db.execute(
            """INSERT INTO class_sessions (
                class_date, weekday, start_time, end_time, subject, batch,
                faculty_name, faculty_id, duration_minutes, reminder_minutes, status,
                google_meet_space_id, google_meet_url, created_at, updated_at
            ) VALUES (
                ?, 'Thursday', '13:30', '14:30', 'Study group review', 'CS-2A',
                'Priya Menon', 1, 60, 15, 'scheduled',
                'spaces/cs2a-study-group', 'https://meet.google.com/xuv-mbna-rtz', ?, ?
            )""",
            (today_str, stamp, stamp)
        )
        db.execute(
            """INSERT INTO class_sessions (
                class_date, weekday, start_time, end_time, subject, batch,
                faculty_name, faculty_id, duration_minutes, reminder_minutes, status,
                google_meet_space_id, google_meet_url, created_at, updated_at
            ) VALUES (
                ?, 'Thursday', '16:00', '17:00', 'Database Systems', 'CS-2A',
                'Dr. Nandita Bose', 3, 60, 15, 'scheduled',
                'spaces/cs2a-db-systems', 'https://meet.google.com/qwa-bgtc-vfr', ?, ?
            )""",
            (today_str, stamp, stamp)
        )

    # 4. Seed sample assignments if needed
    assign_count = db.execute("SELECT count(*) FROM assignments WHERE batch_id='CS-2A'").fetchone()[0]
    if assign_count == 0:
        deadline_3d = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%dT23:59:00Z")
        deadline_7d = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%dT23:59:00Z")
        db.execute(
            """INSERT INTO assignments (title, description, subject, subject_id, batch_id, deadline, faculty_id, faculty_name, created_at, updated_at)
               VALUES ('Assignment 3: Graph Traversal', 'Implement Breadth-First Search (BFS) and Depth-First Search (DFS) algorithms with graph cycle detection.', 'Data Structures', 'CS-201', 'CS-2A', ?, 1, 'Priya Menon', ?, ?)""",
            (deadline_3d, stamp, stamp)
        )
        db.execute(
            """INSERT INTO assignments (title, description, subject, subject_id, batch_id, deadline, faculty_id, faculty_name, created_at, updated_at)
               VALUES ('Assignment 4: Dijkstra Shortest Path', 'Construct shortest path trees using Priority Queue and Fibonacci Heap implementations.', 'Data Structures', 'CS-201', 'CS-2A', ?, 1, 'Priya Menon', ?, ?)""",
            (deadline_7d, stamp, stamp)
        )

    thread_count = db.execute("SELECT count(*) FROM threads").fetchone()[0]
    if thread_count == 0:
        db.execute(
            """INSERT INTO threads (title, body, scope_type, batch_id, subject, recipient_faculty_id,
                author_id, author_name, author_role, created_at, updated_at)
               VALUES (?, ?, 'public', NULL, NULL, NULL, ?, ?, 'STUDENT', ?, ?)""",
            (
                "What is the intuition behind Dijkstra?",
                "Can someone explain Dijkstra in plain language with a campus-map analogy?",
                "std-001",
                "Arjun Rao",
                stamp,
                stamp,
            ),
        )
        db.execute(
            """INSERT INTO threads (title, body, scope_type, batch_id, subject, recipient_faculty_id,
                author_id, author_name, author_role, created_at, updated_at)
               VALUES (?, ?, 'batch', 'CS-2A', 'Data Structures', NULL, ?, ?, 'FACULTY', ?, ?)""",
            (
                "Office hours before Assignment 3",
                "CS-2A Data Structures: extra office hours this week. Bring graph traversal questions.",
                "1",
                "Priya Menon",
                stamp,
                stamp,
            ),
        )
        db.execute(
            """INSERT INTO threads (title, body, scope_type, batch_id, subject, recipient_faculty_id,
                author_id, author_name, author_role, created_at, updated_at)
               VALUES (?, ?, 'private', NULL, NULL, 1, ?, ?, 'STUDENT', ?, ?)""",
            (
                "Clarification on cycle detection",
                "Professor, could you review my DSU approach for cycle detection privately?",
                "std-003",
                "Karan Verma",
                stamp,
                stamp,
            ),
        )

def initialize():
    with connect() as db:
        db.executescript(SCHEMA)
        # Ensure migration columns for all existing tables
        _add_column_if_missing(db, "users", "password_hash", "TEXT")
        _add_column_if_missing(db, "faculty", "phone", "TEXT")
        _add_column_if_missing(db, "class_sessions", "google_meet_space_id", "TEXT")
        _add_column_if_missing(db, "class_sessions", "google_meet_url", "TEXT")
        _add_column_if_missing(db, "class_sessions", "faculty_id", "INTEGER")
        _add_column_if_missing(db, "class_sessions", "is_conducted", "INTEGER DEFAULT 0")
        _add_column_if_missing(db, "assignments", "subject", "TEXT")
        _add_column_if_missing(db, "assignments", "faculty_id", "INTEGER")
        _add_column_if_missing(db, "assignments", "faculty_name", "TEXT")
        _add_column_if_missing(db, "assignments", "updated_at", "TEXT")
        _add_column_if_missing(db, "assignments", "reference_file_path", "TEXT")
        _add_column_if_missing(db, "assignments", "reference_filename", "TEXT")
        _add_column_if_missing(db, "submissions", "student_name", "TEXT")
        _add_column_if_missing(db, "submissions", "original_filename", "TEXT DEFAULT 'submission.pdf'")
        _add_column_if_missing(db, "delivery_log", "channel", "TEXT")
        _add_column_if_missing(db, "delivery_log", "assignment_id", "INTEGER")
        _add_column_if_missing(db, "assignment_reminder_logs", "reminder_type", "TEXT")
        _add_column_if_missing(db, "attendance_records", "verified_by_faculty", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(db, "threads", "scope_type", "TEXT")
        _add_column_if_missing(db, "threads", "batch_id", "TEXT")
        _add_column_if_missing(db, "threads", "subject", "TEXT")
        _add_column_if_missing(db, "threads", "recipient_faculty_id", "INTEGER")
        _add_column_if_missing(db, "threads", "body", "TEXT")
        seed_default_data(db)
