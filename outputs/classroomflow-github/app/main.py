import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from google_auth_oauthlib.flow import Flow
from starlette.middleware.sessions import SessionMiddleware

from .config import (
    APP_MODE,
    APP_SESSION_SECRET,
    EMAIL_DELIVERY_ALLOWED,
    GOOGLE_OAUTH_CLIENT_ID,
    GOOGLE_OAUTH_CLIENT_SECRET,
    GOOGLE_OAUTH_CONFIGURED,
    GOOGLE_OAUTH_REDIRECT_URI,
    MEET_CREATION_ALLOWED,
    TEST_RECIPIENT_ALLOWLIST,
    UPLOAD_DIR,
)
from .db import connect, initialize, now
from .gmail_sender import send_email
from .google_meet import create_meeting_space
from .timetable_parser import parse_timetable

ROOT = Path(__file__).resolve().parents[1]
TIMEZONE = ZoneInfo("Asia/Kolkata")
scheduler = BackgroundScheduler(timezone=TIMEZONE)

app = FastAPI(title="ClassroomFlow")
app.add_middleware(SessionMiddleware, secret_key=APP_SESSION_SECRET, https_only=False)


def as_dict(item):
    return dict(item) if item else None


def oauth_flow():
    client = {
        "web": {
            "client_id": GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_OAUTH_REDIRECT_URI],
        }
    }
    scopes = [
        "https://www.googleapis.com/auth/meetings.space.created",
        "https://www.googleapis.com/auth/gmail.send",
    ]
    return Flow.from_client_config(client, scopes=scopes, redirect_uri=GOOGLE_OAUTH_REDIRECT_URI)


def saved_credentials() -> str:
    with connect() as db:
        row = db.execute("SELECT credentials_json FROM google_credentials WHERE id=1").fetchone()
    if not row:
        raise RuntimeError("Connect your Google account first.")
    return row["credentials_json"]


def check_test_recipients(recipients: list[str]) -> list[str]:
    clean = [item.strip().lower() for item in recipients if item and item.strip()]
    rejected = [item for item in clean if item not in TEST_RECIPIENT_ALLOWLIST]
    if not EMAIL_DELIVERY_ALLOWED:
        raise HTTPException(403, "Email delivery is disabled or TEST_RECIPIENT_ALLOWLIST is empty.")
    if not clean or rejected:
        raise HTTPException(403, "Test mode permits only addresses in TEST_RECIPIENT_ALLOWLIST.")
    return list(dict.fromkeys(clean))


def meeting_for(session_id: int) -> dict:
    with connect() as db:
        item = db.execute("SELECT * FROM class_sessions WHERE id=?", (session_id,)).fetchone()
        if not item:
            raise HTTPException(404, "Class not found")
        if item["google_meet_space_id"]:
            return {
                "space_id": item["google_meet_space_id"],
                "meeting_url": item["google_meet_url"],
                "created": False,
            }
        if not MEET_CREATION_ALLOWED:
            raise HTTPException(403, "Google Meet creation is disabled.")
        try:
            meeting = create_meeting_space(saved_credentials())
        except RuntimeError as error:
            raise HTTPException(401, str(error)) from error
        db.execute(
            "UPDATE class_sessions SET google_meet_space_id=?, google_meet_url=?, updated_at=? WHERE id=?",
            (meeting["space_id"], meeting["meeting_url"], now(), session_id),
        )
        db.execute(
            "INSERT INTO delivery_log(class_session_id, action, status, detail, created_at) VALUES(?, 'google_meet_created', 'success', 'No email sent.', ?)",
            (session_id, now()),
        )
    return {**meeting, "created": True}


def email_body(session: dict, kind: str) -> tuple[str, str]:
    title = f"{session['subject']} · {session['batch'] or 'All batches'}"
    when = f"{session['class_date']} at {session['start_time']}"
    if kind == "reminder":
        return (
            f"Reminder: {title} starts in {session['reminder_minutes']} minutes",
            f"This is a reminder for {title}.\n\nStarts: {when}\nJoin Google Meet: {session['google_meet_url']}",
        )
    return (
        f"Class invite: {title}",
        f"You are invited to {title}.\n\nDate and time: {when}\nFaculty: {session['faculty_name'] or 'To be confirmed'}\nJoin Google Meet: {session['google_meet_url']}",
    )


def send_to_allowlisted_recipients(session_id: int, recipients: list[str], kind: str) -> list[str]:
    recipients = check_test_recipients(recipients)
    with connect() as db:
        session = as_dict(db.execute("SELECT * FROM class_sessions WHERE id=?", (session_id,)).fetchone())
    if not session or not session.get("google_meet_url"):
        raise RuntimeError("Create the Google Meet link before sending email.")
    subject, body = email_body(session, kind)
    message_ids = [send_email(saved_credentials(), recipient, subject, body) for recipient in recipients]
    with connect() as db:
        for recipient, message_id in zip(recipients, message_ids):
            db.execute(
                "INSERT INTO delivery_log(class_session_id, action, status, detail, created_at) VALUES(?, ?, 'sent', ?, ?)",
                (session_id, f"gmail_{kind}", f"{recipient}: {message_id}", now()),
            )
    return message_ids


def run_reminder(session_id: int):
    with connect() as db:
        item = db.execute("SELECT * FROM reminder_jobs WHERE class_session_id=?", (session_id,)).fetchone()
        if not item or item["status"] != "scheduled":
            return
    try:
        send_to_allowlisted_recipients(session_id, TEST_RECIPIENT_ALLOWLIST, "reminder")
        status = "sent"
    except Exception as error:
        status = f"failed: {error}"
    with connect() as db:
        db.execute(
            "UPDATE reminder_jobs SET status=?, updated_at=? WHERE class_session_id=?",
            (status, now(), session_id),
        )


def schedule_reminder(session_id: int):
    with connect() as db:
        session = db.execute(
            "SELECT class_date, start_time, reminder_minutes FROM class_sessions WHERE id=?",
            (session_id,),
        ).fetchone()
    if not session or not session["class_date"]:
        return None
    send_at = datetime.fromisoformat(f"{session['class_date']}T{session['start_time']}").replace(
        tzinfo=TIMEZONE
    ) - timedelta(minutes=session["reminder_minutes"])
    if send_at <= datetime.now(TIMEZONE):
        return None
    scheduler.add_job(
        run_reminder,
        "date",
        run_date=send_at,
        args=[session_id],
        id=f"reminder-{session_id}",
        replace_existing=True,
    )
    with connect() as db:
        db.execute(
            """INSERT INTO reminder_jobs(class_session_id, send_at, status, created_at, updated_at)
               VALUES(?, ?, 'scheduled', ?, ?)
               ON CONFLICT(class_session_id) DO UPDATE SET send_at=excluded.send_at, status='scheduled', updated_at=excluded.updated_at""",
            (session_id, send_at.isoformat(), now(), now()),
        )
    return send_at.isoformat()


def restore_reminders():
    with connect() as db:
        jobs = db.execute("SELECT class_session_id, send_at FROM reminder_jobs WHERE status='scheduled'").fetchall()
    for job in jobs:
        send_at = datetime.fromisoformat(job["send_at"])
        if send_at > datetime.now(TIMEZONE):
            scheduler.add_job(
                run_reminder,
                "date",
                run_date=send_at,
                args=[job["class_session_id"]],
                id=f"reminder-{job['class_session_id']}",
                replace_existing=True,
            )


@app.on_event("startup")
def startup():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    initialize()
    scheduler.start()
    restore_reminders()
    # Schedule assignment reminders check every 4 hours
    from .services.reminders import check_and_send_assignment_reminders

    scheduler.add_job(
        check_and_send_assignment_reminders,
        "interval",
        hours=4,
        id="assignment-reminders",
        replace_existing=True,
    )


@app.on_event("shutdown")
def shutdown():
    scheduler.shutdown(wait=False)


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "mode": APP_MODE,
        "google_meet_creation_allowed": MEET_CREATION_ALLOWED,
        "gmail_test_delivery_allowed": EMAIL_DELIVERY_ALLOWED,
        "calendar_used": False,
    }


@app.get("/auth/google/start")
def google_start(request: Request):
    if not GOOGLE_OAUTH_CONFIGURED:
        raise HTTPException(400, "Add your real Google OAuth values to .env first.")
    flow = oauth_flow()
    url, state = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent")
    request.session["oauth_state"] = state
    request.session["code_verifier"] = flow.code_verifier
    return RedirectResponse(url)


@app.get("/auth/google/callback")
def google_callback(request: Request, state: str | None = None, code: str | None = None):
    if not code or state != request.session.get("oauth_state"):
        raise HTTPException(400, "Invalid Google OAuth callback state.")
    flow = oauth_flow()
    code_verifier = request.session.get("code_verifier")
    flow.fetch_token(code=code, code_verifier=code_verifier)
    with connect() as db:
        db.execute(
            "INSERT INTO google_credentials(id, credentials_json, updated_at) VALUES(1, ?, ?) ON CONFLICT(id) DO UPDATE SET credentials_json=excluded.credentials_json, updated_at=excluded.updated_at",
            (flow.credentials.to_json(), now()),
        )
    return RedirectResponse("/")


@app.get("/api/classes")
def list_classes():
    with connect() as db:
        return [
            as_dict(item)
            for item in db.execute("SELECT * FROM class_sessions ORDER BY class_date, weekday, start_time")
        ]


@app.post("/api/timetables/upload")
async def upload_timetable(
    file: UploadFile = File(...),
    schedule_type: str = Form(...),
    effective_date: str | None = Form(None),
):
    if schedule_type not in {"daily", "weekly"}:
        raise HTTPException(400, "schedule_type must be daily or weekly")
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Upload an .xlsx timetable")
    path = UPLOAD_DIR / f"{now().replace(':', '-')}_{Path(file.filename).name}"
    with path.open("wb") as destination:
        shutil.copyfileobj(file.file, destination)
    parsed = parse_timetable(path)
    if not parsed:
        raise HTTPException(400, "No class entries found")
    stamp = now()
    with connect() as db:
        timetable = db.execute(
            "INSERT INTO timetables(filename, schedule_type, effective_date, uploaded_at) VALUES(?, ?, ?, ?)",
            (file.filename, schedule_type, effective_date, stamp),
        )
        for item in parsed:
            db.execute(
                """INSERT INTO class_sessions(
                    timetable_id, class_date, weekday, start_time, end_time,
                    subject, batch, faculty_name, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    timetable.lastrowid,
                    effective_date,
                    item.weekday,
                    item.start_time,
                    item.end_time,
                    item.subject,
                    item.batch,
                    item.faculty_name,
                    stamp,
                    stamp,
                ),
            )
    return {"classes_detected": len(parsed), "delivery_performed": False}


def save_sudden_class_to_db(payload: dict, meeting_url: str | None, space_id: str | None) -> int:
    stamp = now()
    date_str = payload.get("class_date")
    try:
        if isinstance(date_str, str):
            weekday = datetime.fromisoformat(date_str).strftime("%A")
        else:
            weekday = "Monday"
    except (ValueError, TypeError):
        weekday = "Monday"
    with connect() as db:
        cursor = db.execute(
            """INSERT INTO class_sessions(
                class_date, weekday, start_time, end_time, subject, batch, faculty_name,
                duration_minutes, reminder_minutes, status, google_meet_space_id, google_meet_url,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?, ?, ?, ?)""",
            (
                payload.get("class_date"),
                weekday,
                payload.get("start_time"),
                payload.get("end_time"),
                payload.get("subject"),
                payload.get("batch"),
                payload.get("faculty_name"),
                payload.get("duration_minutes", 60),
                payload.get("reminder_minutes", 10),
                space_id,
                meeting_url,
                stamp,
                stamp,
            ),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("Database insert failed")
        return cursor.lastrowid


def get_batch_student_emails(batch: str | None) -> list[str]:
    if not batch:
        return []
    with connect() as db:
        rows = db.execute(
            """SELECT DISTINCT s.email FROM students s
               JOIN batch_allocations b ON s.id = b.roll_no
               WHERE b.batch = ? AND s.active = 1""",
            (batch,),
        ).fetchall()
        return [row["email"] for row in rows if row["email"]]


@app.post("/api/classes/sudden")
def create_sudden_class(payload: dict):
    # 1. Validate required fields
    required = ["class_date", "start_time", "subject"]
    for field in required:
        if field not in payload or not payload[field]:
            raise HTTPException(status_code=400, detail=f"'{field}' is required")

    # 2. Automatically generate Google Meet link
    try:
        meet_data = create_meeting_space(saved_credentials())
        meeting_url = meet_data["meeting_url"]
        space_id = meet_data["space_id"]
    except Exception:
        meeting_url = None
        space_id = None

    # 3. Save class record to DB
    session_id = save_sudden_class_to_db(payload, meeting_url, space_id)

    # 4. Auto-dispatch email invites to replacement faculty and students
    recipients = [payload.get("faculty_email")] + get_batch_student_emails(payload.get("batch"))
    recipients = [r for r in recipients if r]

    message_ids = []
    if recipients and meeting_url:
        subject_line = f"URGENT: Substitute Class Scheduled - {payload.get('subject')}"
        body_text = f"A replacement class for {payload.get('subject')} has been scheduled for {payload.get('class_date')} at {payload.get('start_time')}.\n\nJoin Google Meet: {meeting_url}"

        for recipient in recipients:
            msg_id = send_email(saved_credentials(), recipient, subject_line, body_text)
            message_ids.append(msg_id)

    return {
        "status": "success",
        "session_id": session_id,
        "meeting_url": meeting_url,
        "emails_sent_to": len(message_ids),
    }


@app.post("/api/classes/{session_id}/create-google-meet")
def create_google_meet(session_id: int):
    return meeting_for(session_id)


@app.post("/api/classes/{session_id}/send-test-invite")
def send_test_invite(session_id: int, payload: dict):
    meeting_for(session_id)
    recipients = payload.get("recipients", TEST_RECIPIENT_ALLOWLIST)
    message_ids = send_to_allowlisted_recipients(session_id, recipients, "invite")
    reminder_at = schedule_reminder(session_id)
    return {"message_ids": message_ids, "reminder_scheduled_for": reminder_at, "calendar_used": False}


@app.post("/api/classes/{session_id}/send-test-reminder-now")
def send_test_reminder_now(session_id: int):
    message_ids = send_to_allowlisted_recipients(session_id, TEST_RECIPIENT_ALLOWLIST, "reminder")
    return {"message_ids": message_ids, "calendar_used": False}


@app.post("/api/assignments")
def create_assignment(payload: dict):
    required = ["title", "deadline", "subject_id", "batch_id"]
    for field in required:
        if field not in payload or not payload[field]:
            raise HTTPException(status_code=400, detail=f"'{field}' is required")
    stamp = now()
    with connect() as db:
        cursor = db.execute(
            """INSERT INTO assignments (title, description, subject_id, batch_id, deadline, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                payload["title"],
                payload.get("description"),
                payload["subject_id"],
                payload["batch_id"],
                payload["deadline"],
                stamp,
            )
        )
        assignment_id = cursor.lastrowid
        row = db.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        return as_dict(row)


@app.post("/api/assignments/{assignment_id}/submit")
async def submit_assignment(assignment_id: int, file: UploadFile = File(...), student_id: str = Form(...)):
    with connect() as db:
        assignment = db.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found")
        student = db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")

    filename = file.filename or "submission"
    ext = Path(filename).suffix.lower()
    if ext not in {".pdf", ".png", ".jpg", ".jpeg", ".gif"}:
        raise HTTPException(status_code=400, detail="Submission file must be a PDF or an Image (PNG, JPG, JPEG, GIF)")

    sub_dir = UPLOAD_DIR / "submissions"
    sub_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{assignment_id}_{student_id}_{Path(filename).name}"
    file_path = sub_dir / safe_name
    with file_path.open("wb") as destination:
        shutil.copyfileobj(file.file, destination)

    stamp = now()
    with connect() as db:
        cursor = db.execute(
            """INSERT INTO submissions (assignment_id, student_id, file_path, submitted_at)
               VALUES (?, ?, ?, ?)""",
            (assignment_id, student_id, str(file_path), stamp),
        )
        submission_id = cursor.lastrowid
        row = db.execute("SELECT * FROM submissions WHERE id = ?", (submission_id,)).fetchone()
        return as_dict(row)


@app.get("/api/assignments/{assignment_id}/submissions")
def get_submissions(assignment_id: int):
    with connect() as db:
        assignment = db.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found")
        rows = db.execute("SELECT * FROM submissions WHERE assignment_id = ?", (assignment_id,)).fetchall()
        return [as_dict(r) for r in rows]


@app.post("/api/reminders/trigger")
def trigger_reminders():
    from .services.reminders import check_and_send_assignment_reminders

    check_and_send_assignment_reminders()
    return {"status": "success", "detail": "Reminder check triggered"}


app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")