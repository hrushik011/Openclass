import hashlib
import json
import logging
import re
import secrets
import shutil
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from google_auth_oauthlib.flow import Flow
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from .auth import (
    authenticate_user,
    get_current_user,
    get_optional_current_user,
    require_faculty,
    require_student,
    verify_and_provision_ms_user,
)
from .config import (
    APP_MODE,
    APP_SESSION_SECRET,
    EMAIL_DELIVERY_ALLOWED,
    EMAIL_DELIVERY_ENABLED,
    GOOGLE_OAUTH_CLIENT_ID,
    GOOGLE_OAUTH_CLIENT_SECRET,
    GOOGLE_OAUTH_CONFIGURED,
    GOOGLE_OAUTH_REDIRECT_URI,
    MEET_CREATION_ALLOWED,
    MS_CLIENT_ID,
    MS_CLIENT_SECRET,
    MS_REDIRECT_URI,
    TEST_RECIPIENT_ALLOWLIST,
    UPLOAD_DIR,
    microsoft_oauth_tenant,
)
from .db import connect, initialize, now
from .gmail_sender import send_email
from .google_meet import build_meeting_launch_url, create_meeting_space
from .services.assignment import (
    create_assignment_zip_archive,
    save_assignment_reference_file,
    save_student_submission,
)
from .services.notification import NotificationService
from .services.reminders import check_and_send_assignment_reminders
from .services.roster import (
    is_generalist_user,
    list_batches_for_subject,
    list_subjects_for_user,
    rebuild_faculty_subject_batches,
    roster_status,
    _session_exists,
)
from .timetable_parser import parse_timetable


logger = logging.getLogger("openclass.main")
ROOT = Path(__file__).resolve().parents[1]
TIMEZONE = ZoneInfo("Asia/Kolkata")

scheduler = BackgroundScheduler(timezone=TIMEZONE)
app = FastAPI(title="Openclass Platform", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SessionMiddleware, secret_key=APP_SESSION_SECRET, https_only=False)


def as_dict(item):
    return dict(item) if item else None


# Whether real Microsoft Entra ID (Azure AD) credentials are configured
MS_CONFIGURED = bool(MS_CLIENT_ID and MS_CLIENT_SECRET)


def ms_authorization_url(state: str, role: str = "STUDENT") -> str:
    """Build the Microsoft Entra ID authorization URL for OIDC login."""
    params = {
        "client_id": MS_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": MS_REDIRECT_URI,
        "response_mode": "query",
        "scope": "openid profile email User.Read",
        "state": f"{state}:{role}",  # encode role in state
        "prompt": "select_account",
    }
    tenant = microsoft_oauth_tenant()
    base = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
    return f"{base}?{urllib.parse.urlencode(params)}"


def ms_exchange_code(code: str) -> dict:
    """Exchange MS auth code for tokens. Returns decoded id_token claims dict."""
    import base64
    import requests as req

    tenant = microsoft_oauth_tenant()
    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    resp = req.post(
        token_url,
        data={
            "grant_type": "authorization_code",
            "client_id": MS_CLIENT_ID,
            "client_secret": MS_CLIENT_SECRET,
            "code": code,
            "redirect_uri": MS_REDIRECT_URI,
        },
        timeout=15,
    )
    resp.raise_for_status()
    token_data = resp.json()

    # Decode id_token payload (second segment, base64url)
    id_token = token_data.get("id_token", "")
    if not id_token:
        raise ValueError("No id_token in Microsoft token response")

    payload_b64 = id_token.split(".")[1]
    # Pad to multiple of 4
    payload_b64 += "=" * (4 - len(payload_b64) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload_b64).decode())
    return claims



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
        "https://www.googleapis.com/auth/calendar.events",
    ]
    return Flow.from_client_config(client, scopes=scopes, redirect_uri=GOOGLE_OAUTH_REDIRECT_URI)


def saved_credentials() -> Optional[str]:
    try:
        with connect() as db:
            row = db.execute("SELECT credentials_json FROM google_credentials WHERE id=1").fetchone()
            if row:
                return row["credentials_json"]
    except Exception:
        pass
    return None


def get_batch_student_recipients(batch_id: str) -> list[dict]:
    if not batch_id:
        return []
    with connect() as db:
        rows = db.execute(
            """SELECT DISTINCT s.id, s.name, s.email, s.phone FROM students s
               LEFT JOIN batch_allocations b ON s.id = b.roll_no
               WHERE (s.batch_id = ? OR b.batch = ? OR ? LIKE '%' || s.batch_id || '%') AND s.active = 1""",
            (batch_id, batch_id, batch_id),
        ).fetchall()
        return [dict(r) for r in rows if r["email"]]


def recipients_for_subject_batch(subject: str, batch_id: Optional[str] = None) -> list[dict]:
    if not batch_id or str(batch_id).strip().lower() in {"all batches", "all", "*"}:
        return get_notes_student_recipients(subject)
    return get_batch_student_recipients(str(batch_id).strip())


def get_notes_student_recipients(subject: str, specialization: Optional[str] = None) -> list[dict]:
    """Students enrolled in a subject/specialization across all batches."""
    if not subject:
        return []
    with connect() as db:
        sql = """
            SELECT DISTINCT s.id, s.name, s.email, s.phone
            FROM students s
            LEFT JOIN batch_allocations b ON s.id = b.roll_no
            WHERE s.active = 1
              AND (b.subject = ? OR b.subject LIKE '%' || ? || '%')
        """
        params: list = [subject, subject]
        if specialization and str(specialization).strip().lower() not in {"all batches", "all", "*"}:
            sql += """
              AND (
                b.batch = ?
                OR s.batch_id = ?
                OR b.subject LIKE '%' || ? || '%'
                OR s.batch_id LIKE '%' || ? || '%'
              )
            """
            params.extend([specialization, specialization, specialization, specialization])
        rows = db.execute(sql, params).fetchall()
        return [dict(r) for r in rows if r["email"]]


def meeting_for(session_id: int) -> dict:
    with connect() as db:
        item = db.execute("SELECT * FROM class_sessions WHERE id=?", (session_id,)).fetchone()
        if not item:
            raise HTTPException(404, "Class session not found")
        item_dict = dict(item)
        if item_dict.get("google_meet_url"):
            return {
                "space_id": item_dict.get("google_meet_space_id"),
                "meeting_url": item_dict.get("google_meet_url"),
                "faculty_host_url": f"{item_dict.get('google_meet_url')}?authuser={item_dict.get('faculty_name', '')}&hs=122",
                "created": False,
                "host_controls": {
                    "sole_host": True,
                    "host_faculty": item_dict.get("faculty_name"),
                    "restricted_students": True,
                },
            }

        creds = saved_credentials()
        meeting = create_meeting_space(
            credentials_json_str=creds,
            faculty_email=item_dict.get("faculty_name"),
            subject=item_dict.get("subject"),
        )
        db.execute(
            "UPDATE class_sessions SET google_meet_space_id=?, google_meet_url=?, updated_at=? WHERE id=?",
            (meeting["space_id"], meeting["meeting_url"], now(), session_id),
        )
        db.execute(
            "INSERT INTO delivery_log(class_session_id, action, status, detail, created_at) VALUES(?, 'google_meet_created', 'success', ?, ?)",
            (session_id, f"URL: {meeting['meeting_url']} · Host: {meeting['host_email']}", now()),
        )
    return {**meeting, "created": True}


# --- Lifecycle Events ---


@app.on_event("startup")
def startup():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    initialize()
    try:
        rebuild_faculty_subject_batches()
    except Exception as exc:
        logger.warning("Could not rebuild faculty subject roster: %s", exc)
    try:
        scheduler.start()
        # Schedule assignment reminder job every 2 hours
        scheduler.add_job(
            check_and_send_assignment_reminders,
            "interval",
            hours=2,
            id="assignment-reminders-job",
            replace_existing=True,
        )
    except Exception as e:
        logger.warning(f"Scheduler startup warning: {e}")


@app.on_event("shutdown")
def shutdown():
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass


# --- Authentication & RBAC Routes ---


class LoginRequest(BaseModel):
    email: str
    password: str
    role: Optional[str] = "STUDENT"  # "STUDENT" or "FACULTY"


class MicrosoftAuthRequest(BaseModel):
    email: str
    name: Optional[str] = None
    role: Optional[str] = "STUDENT"
    batch_id: Optional[str] = None
    phone: Optional[str] = None
    id_token: Optional[str] = None


@app.post("/api/auth/login")
def login(payload: LoginRequest):
    """
    Password login with explicit tabs for 'Student' and 'Faculty'.
    Enforces role separation and returns JWT session token.
    """
    if not payload.email or not payload.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email and password are required.",
        )
    return authenticate_user(payload.email, payload.password, payload.role)


@app.post("/api/auth/microsoft")
def microsoft_sso(payload: MicrosoftAuthRequest):
    """
    Microsoft Outlook / Office 365 OIDC authentication.
    Parses user institutional claims and provisions or routes them.
    """
    if not payload.email:
        raise HTTPException(status_code=400, detail="Microsoft email is required.")
    name = payload.name or payload.email.split("@")[0].replace(".", " ").title()
    role = (payload.role or "STUDENT").upper()
    return verify_and_provision_ms_user(
        email=payload.email,
        name=name,
        role=role,
        batch_id=payload.batch_id,
        phone=payload.phone,
    )


@app.get("/api/auth/me")
def current_user_profile(user: dict = Depends(get_current_user)):
    """Return the authenticated user identity and workspace role."""
    return user


# --- Google OAuth Endpoints ---


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
            """INSERT INTO google_credentials(id, credentials_json, updated_at)
               VALUES(1, ?, ?)
               ON CONFLICT(id) DO UPDATE SET credentials_json=excluded.credentials_json, updated_at=excluded.updated_at""",
            (flow.credentials.to_json(), now()),
        )
    return RedirectResponse("/")


# --- Microsoft Entra ID (Azure AD) OIDC Routes ---


@app.get("/auth/microsoft/start")
def microsoft_start(request: Request, role: str = "STUDENT"):
    """
    Initiate real Microsoft Entra ID / Office 365 OIDC login.
    Redirects to Azure AD consent page. Falls back to demo mode if creds are missing.
    """
    if not MS_CONFIGURED:
        raise HTTPException(
            400,
            detail=(
                "Microsoft SSO is not yet configured. "
                "Add MS_CLIENT_ID, MS_CLIENT_SECRET, and AZURE_TENANT_ID to your .env file. "
                "See .env.example for reference."
            ),
        )
    state = secrets.token_urlsafe(24)
    request.session["ms_oauth_state"] = state
    request.session["ms_login_role"] = role.upper()
    url = ms_authorization_url(state=state, role=role.upper())
    return RedirectResponse(url)


@app.get("/auth/microsoft/callback")
def microsoft_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
):
    """
    Microsoft Entra ID OIDC callback.
    Validates state, exchanges auth code for id_token, provisions user, returns JWT
    via redirect to / with the token embedded in a short-lived cookie the frontend reads.
    """
    if error:
        logger.error(f"MS OAuth error: {error} — {error_description}")
        return RedirectResponse(f"/?ms_error={urllib.parse.quote(error_description or error)}")

    stored_state = request.session.get("ms_oauth_state")
    if not state or not stored_state or not state.startswith(stored_state):
        return RedirectResponse("/?ms_error=invalid_state")

    if not code:
        return RedirectResponse("/?ms_error=no_code")

    # Determine role from state suffix or session
    role = request.session.get("ms_login_role", "STUDENT")
    if ":" in state:
        role = state.split(":", 1)[1].upper()

    try:
        claims = ms_exchange_code(code)
    except Exception as exc:
        logger.error(f"MS token exchange failed: {exc}")
        return RedirectResponse(f"/?ms_error={urllib.parse.quote(str(exc))}")

    email = claims.get("email") or claims.get("preferred_username") or claims.get("upn")
    name = claims.get("name") or (email.split("@")[0].replace(".", " ").title() if email else "Unknown")

    if not email:
        return RedirectResponse("/?ms_error=no_email_in_token")

    try:
        result = verify_and_provision_ms_user(email=email, name=name, role=role)
    except Exception as exc:
        logger.error(f"MS user provisioning failed: {exc}")
        return RedirectResponse(f"/?ms_error={urllib.parse.quote(str(exc))}")

    token = result["access_token"]
    # Clear state from session
    request.session.pop("ms_oauth_state", None)
    request.session.pop("ms_login_role", None)

    # Pass token to frontend via a short-lived cookie; JS reads & stores in localStorage
    response = RedirectResponse("/?ms_sso=1")
    response.set_cookie(
        key="ms_jwt_handoff",
        value=token,
        max_age=30,          # 30 seconds — frontend reads & clears it immediately
        httponly=False,       # Must be readable by JS
        samesite="lax",
        secure=False,         # Set True in production with HTTPS
    )
    return response


@app.get("/api/auth/ms-status")
def ms_sso_status():
    """Returns whether Microsoft SSO is fully configured with real Azure AD credentials."""
    return {
        "configured": MS_CONFIGURED,
        "tenant_id": microsoft_oauth_tenant() if MS_CONFIGURED else None,
        "start_url": "/auth/microsoft/start",
    }


# --- Class Sessions & Google Meet Integration ---


@app.get("/api/classes")
def list_classes(
    batch: Optional[str] = None,
    current_user: Optional[dict] = Depends(get_optional_current_user),
):
    """
    List scheduled lectures and meetings.
    If student is authenticated, filters by student's batch.
    """
    with connect() as db:
        filter_batch = batch
        if not filter_batch and current_user and str(current_user.get("role")).upper() == "STUDENT":
            filter_batch = current_user.get("batch_id")

        if filter_batch:
            rows = db.execute(
                """SELECT * FROM class_sessions
                   WHERE batch = ? OR subject LIKE '%' || ? || '%'
                   ORDER BY class_date, weekday, start_time""",
                (filter_batch, filter_batch),
            ).fetchall()
        else:
            rows = db.execute("SELECT * FROM class_sessions ORDER BY class_date, weekday, start_time").fetchall()

        result = []
        for r in rows:
            c = dict(r)
            # Decorate with launch url according to viewer
            if c.get("google_meet_url"):
                c["launch_info"] = build_meeting_launch_url(c["google_meet_url"], current_user)
            result.append(c)
        return result


@app.get("/api/classes/{session_id}/meet-link")
def get_session_meet_link(
    session_id: int,
    current_user: Optional[dict] = Depends(get_optional_current_user),
):
    """
    Returns personalized Google Meet launch link passing student Microsoft/institutional
    identity and enforcing strict host controls for faculty.
    """
    meet_info = meeting_for(session_id)
    launch_info = build_meeting_launch_url(meet_info["meeting_url"], current_user)
    return {
        "session_id": session_id,
        "meeting_url": meet_info["meeting_url"],
        "launch_url": launch_info["url"],
        "is_host": launch_info["is_host"],
        "role_badge": launch_info["role_badge"],
        "host_controls": meet_info.get("host_controls"),
        "controls_notice": launch_info.get("controls"),
    }


@app.post("/api/classes/{session_id}/create-google-meet")
def create_class_google_meet(session_id: int):
    """Create or retrieve Google Meet space with strict host controls."""
    return meeting_for(session_id)


@app.post("/api/classes/sudden")
def create_sudden_class(payload: dict, background_tasks: BackgroundTasks):
    """
    Schedule a sudden replacement lecture:
    - Generates instant Google Meet space with faculty as sole host
    - Records class session in database
    - Dispatches urgent email alerts to the batch in the background
    """
    required = ["class_date", "start_time", "subject"]
    for field in required:
        if field not in payload or not payload[field]:
            raise HTTPException(status_code=400, detail=f"'{field}' is required.")

    batch = payload.get("batch") or "CS-2A"
    faculty_name = payload.get("faculty_name") or "Priya Menon"

    # Generate Google Meet space
    creds = saved_credentials()
    meet_data = create_meeting_space(
        credentials_json_str=creds,
        faculty_email=payload.get("faculty_email") or "priya.menon@college.edu",
        subject=payload.get("subject"),
    )
    meeting_url = meet_data["meeting_url"]
    space_id = meet_data["space_id"]

    stamp = now()
    date_str = payload.get("class_date")
    try:
        weekday = datetime.fromisoformat(date_str).strftime("%A")
    except Exception:
        weekday = "Thursday"

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
                payload.get("end_time") or "18:00",
                payload.get("subject"),
                batch,
                faculty_name,
                payload.get("duration_minutes", 60),
                payload.get("reminder_minutes", 15),
                space_id,
                meeting_url,
                stamp,
                stamp,
            ),
        )
        session_id = cursor.lastrowid

    # Background email blast
    recipients = recipients_for_subject_batch(payload.get("subject"), batch)
    if payload.get("faculty_email"):
        recipients.append({"email": payload.get("faculty_email"), "name": faculty_name})

    def dispatch_sudden_class_emails():
        subject_line = f"🚨 Sudden Class Scheduled: {payload.get('subject')} ({batch})"
        body_text = (
            f"A replacement session for {payload.get('subject')} has been scheduled for {payload.get('class_date')} at {payload.get('start_time')}.\n\n"
            f"Join Google Meet (Strict Host Controls Active):\n{meeting_url}\n\n"
            f"Faculty Host: {faculty_name}\n"
            f"Openclass Academic System"
        )
        for r in recipients:
            if r.get("email"):
                NotificationService.send_email(r["email"], subject_line, body_text)

    background_tasks.add_task(dispatch_sudden_class_emails)

    return {
        "status": "success",
        "session_id": session_id,
        "meeting_url": meeting_url,
        "host_controls": meet_data["host_controls"],
        "emails_queued": len(recipients),
    }


# --- Timetable Roster Upload ---


@app.get("/api/subjects")
@app.get("/api/timetable/subjects")
def list_ingested_subjects(
    current_user: Optional[dict] = Depends(get_optional_current_user),
):
    """Course subjects from persisted timetable roster, scoped to the signed-in faculty."""
    role = str((current_user or {}).get("role") or "").upper()
    generalist = is_generalist_user(current_user) or not current_user or role != "FACULTY"
    query_user = current_user or {}
    if generalist:
        query_user = {**query_user, "role": "GENERALIST"}
    subjects = list_subjects_for_user(query_user)
    return {
        "subjects": subjects,
        "generalist": bool(generalist),
        "persisted": True,
    }


@app.get("/api/subjects/batches")
@app.get("/api/timetable/batches")
def list_batches_for_ingested_subject(
    subject: str,
    current_user: Optional[dict] = Depends(get_optional_current_user),
):
    """Batches linked to a course subject in the ingested timetable roster."""
    role = str((current_user or {}).get("role") or "").upper()
    query_user = current_user or {}
    if is_generalist_user(current_user) or not current_user or role != "FACULTY":
        query_user = {**query_user, "role": "GENERALIST"}
    batches = list_batches_for_subject(query_user, subject)
    return {"subject": subject, "batches": batches}


@app.get("/api/roster/status")
def get_roster_status():
    return roster_status()


@app.post("/api/timetables/upload")
@app.post("/api/ingest-timetable")
async def upload_timetable(
    file: UploadFile = File(...),
    schedule_type: str = Form("weekly"),
    effective_date: str | None = Form(None),
):
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Please upload a valid .xlsx or .xlsm timetable.")

    path = UPLOAD_DIR / f"{now().replace(':', '-')}_{Path(file.filename).name}"
    with path.open("wb") as destination:
        shutil.copyfileobj(file.file, destination)

    parsed = parse_timetable(path)
    if not parsed:
        raise HTTPException(400, "No valid lecture entries detected in timetable.")

    stamp = now()
    with connect() as db:
        timetable = db.execute(
            "INSERT INTO timetables(filename, schedule_type, effective_date, uploaded_at) VALUES(?,?,?,?)",
            (file.filename, schedule_type, effective_date, stamp),
        )
        tt_id = timetable.lastrowid
        added = 0
        skipped = 0
        for item in parsed:
            if _session_exists(db, item):
                skipped += 1
                continue
            code = create_meeting_space(subject=item.subject)
            db.execute(
                """INSERT INTO class_sessions(
                    timetable_id, class_date, weekday, start_time, end_time, subject,
                    batch, faculty_name, google_meet_space_id, google_meet_url, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    tt_id,
                    effective_date,
                    item.weekday,
                    item.start_time,
                    item.end_time,
                    item.subject,
                    item.batch,
                    item.faculty_name,
                    code["space_id"],
                    code["meeting_url"],
                    stamp,
                    stamp,
                ),
            )
            added += 1
        rebuild_faculty_subject_batches(db)

    return {
        "status": "success",
        "filename": file.filename,
        "classes_detected": len(parsed),
        "sessions_added": added,
        "sessions_existing": skipped,
        "persisted": True,
        "message": (
            f"Stored {added} new class sessions in the database"
            + (f" ({skipped} already persisted)." if skipped else ".")
        ),
    }


# --- Lecture Notes ---


@app.post("/api/faculty/notes")
async def upload_lecture_notes(
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    subject: str = Form(...),
    specialization: Optional[str] = Form(None),
    file: UploadFile = File(...),
    current_user: Optional[dict] = Depends(get_optional_current_user),
):
    """Faculty uploads lecture notes and notifies enrolled students across batches."""
    if not file.filename:
        raise HTTPException(400, "Please attach a lecture notes file.")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename).name
    dest = UPLOAD_DIR / f"{now().replace(':', '-')}_{safe_name}"
    with dest.open("wb") as destination:
        shutil.copyfileobj(file.file, destination)

    faculty_name = current_user.get("name") if current_user else None
    stamp = now()
    with connect() as db:
        cursor = db.execute(
            """INSERT INTO lecture_notes (
                title, subject, specialization, file_path, original_filename, faculty_name, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (title, subject, specialization, str(dest), safe_name, faculty_name, stamp),
        )
        note_id = cursor.lastrowid
        row = db.execute("SELECT * FROM lecture_notes WHERE id = ?", (note_id,)).fetchone()
        created = dict(row)

    recipients = get_notes_student_recipients(subject, specialization)

    def dispatch_notes_emails():
        subject_line = f"New lecture notes: {title} ({subject})"
        spec_line = f"\nSpecialization: {specialization}" if specialization else ""
        body_text = (
            f"New lecture notes have been uploaded for {subject}.{spec_line}\n\n"
            f"Title: {title}\n"
            f"File: {safe_name}\n"
            f"Faculty: {faculty_name or 'Course Faculty'}\n\n"
            f"Please log into Openclass to download the notes.\n\n"
            f"Openclass Academic System"
        )
        for student in recipients:
            email = student.get("email")
            if email:
                NotificationService.send_email(email, subject_line, body_text)

    background_tasks.add_task(dispatch_notes_emails)

    created["emails_queued"] = len(recipients)
    return created


@app.get("/api/notes")
def list_lecture_notes(
    subject: Optional[str] = None,
    specialization: Optional[str] = None,
):
    with connect() as db:
        sql = "SELECT * FROM lecture_notes WHERE 1=1"
        params: list = []
        if subject:
            sql += " AND subject = ?"
            params.append(subject)
        if specialization:
            sql += " AND specialization = ?"
            params.append(specialization)
        sql += " ORDER BY id DESC"
        rows = db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/notes/{note_id}/file")
def download_lecture_note(note_id: int):
    with connect() as db:
        row = db.execute("SELECT * FROM lecture_notes WHERE id = ?", (note_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Lecture note not found.")
        note = dict(row)
    path = Path(note["file_path"])
    if not path.exists():
        raise HTTPException(404, "Lecture note file is missing on disk.")
    return FileResponse(path, filename=note["original_filename"])


# --- Assignment Portal & Lifecycle Management ---


class AssignmentCreate(BaseModel):
    title: str
    subject: Optional[str] = "Data Structures"
    batch_id: str
    deadline: str  # ISO timestamp
    description: Optional[str] = None


class AssignmentUpdate(BaseModel):
    title: Optional[str] = None
    subject: Optional[str] = None
    batch_id: Optional[str] = None
    deadline: Optional[str] = None
    description: Optional[str] = None


@app.get("/api/assignments")
def list_assignments(
    batch: Optional[str] = None,
    current_user: Optional[dict] = Depends(get_optional_current_user),
):
    """
    List assignments.
    Student Portal Binding: strictly filters active assignments by the student's assigned Batch!
    """
    filter_batch = batch
    user_role = str(current_user.get("role", "")).upper() if current_user else None

    # If student, enforce batch filtering
    if user_role == "STUDENT" and current_user:
        filter_batch = current_user.get("batch_id")

    with connect() as db:
        if filter_batch:
            rows = db.execute(
                """SELECT * FROM assignments
                   WHERE batch_id = ? OR ? LIKE '%' || batch_id || '%'
                   ORDER BY deadline ASC""",
                (filter_batch, filter_batch),
            ).fetchall()
        else:
            rows = db.execute("SELECT * FROM assignments ORDER BY deadline ASC").fetchall()

        assignments = []
        student_id = str(current_user.get("id")) if current_user and user_role == "STUDENT" else None

        for r in rows:
            item = dict(r)
            a_id = item["id"]
            # Submission counts
            sub_count = db.execute(
                "SELECT count(*) FROM submissions WHERE assignment_id = ?",
                (a_id,),
            ).fetchone()[0]

            # Total batch students
            total_students = db.execute(
                """SELECT count(DISTINCT s.id) FROM students s
                   WHERE s.batch_id = ? OR ? LIKE '%' || s.batch_id || '%'""",
                (item["batch_id"], item["batch_id"]),
            ).fetchone()[0]
            if total_students == 0:
                total_students = 42  # default batch size display

            item["submission_count"] = sub_count
            item["total_students"] = total_students
            item["has_reference_file"] = bool(item.get("reference_filename") or item.get("reference_file_path"))

            # Student specific submission state
            item["has_submitted"] = False
            item["submission_details"] = None
            if student_id:
                sub_row = db.execute(
                    "SELECT * FROM submissions WHERE assignment_id = ? AND student_id = ?",
                    (a_id, student_id),
                ).fetchone()
                if sub_row:
                    item["has_submitted"] = True
                    item["submission_details"] = dict(sub_row)

            # Deadline status calculation
            try:
                deadline_clean = item["deadline"].replace("Z", "+00:00")
                deadline_dt = datetime.fromisoformat(deadline_clean)
                if deadline_dt.tzinfo is None:
                    deadline_dt = deadline_dt.replace(tzinfo=timezone.utc)
                diff = deadline_dt - datetime.now(timezone.utc)
                item["hours_remaining"] = round(diff.total_seconds() / 3600.0, 1)
                item["is_expired"] = diff.total_seconds() <= 0
            except Exception:
                item["hours_remaining"] = 72
                item["is_expired"] = False

            assignments.append(item)

        return assignments


def persist_new_assignment(
    title: str,
    subject: str,
    batch_id: str,
    deadline: str,
    description: Optional[str],
    faculty_id,
    faculty_name: str,
    assignment_file: Optional[UploadFile] = None,
) -> dict:
    stamp = now()
    with connect() as db:
        cursor = db.execute(
            """INSERT INTO assignments (
                title, description, subject, subject_id, batch_id, deadline,
                faculty_id, faculty_name, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                title,
                description,
                subject,
                "CS-201",
                batch_id,
                deadline,
                faculty_id,
                faculty_name,
                stamp,
                stamp,
            ),
        )
        assignment_id = cursor.lastrowid

        file_path = None
        original_name = None
        if assignment_file and assignment_file.filename:
            file_path, original_name = save_assignment_reference_file(assignment_file, assignment_id)
            db.execute(
                """UPDATE assignments
                   SET reference_file_path = ?, reference_filename = ?
                   WHERE id = ?""",
                (file_path, original_name, assignment_id),
            )

        row = db.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        return dict(row)


@app.post("/api/assignments")
async def create_assignment(
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    subject: Optional[str] = Form("Data Structures"),
    batch_id: str = Form(...),
    deadline: str = Form(...),
    description: Optional[str] = Form(None),
    assignment_file: Optional[UploadFile] = File(None),
    current_user: Optional[dict] = Depends(get_optional_current_user),
):
    """
    Faculty creates a new assignment portal, optionally attaching a reference file
    (PDF / Word / Excel) for the target student batch.
    """
    faculty_id = current_user.get("id") if current_user else 1
    faculty_name = current_user.get("name") if current_user else "Priya Menon"

    created = persist_new_assignment(
        title=title,
        subject=subject or "Data Structures",
        batch_id=batch_id,
        deadline=deadline,
        description=description,
        faculty_id=faculty_id,
        faculty_name=faculty_name,
        assignment_file=assignment_file,
    )

    target_students = recipients_for_subject_batch(subject or "", batch_id)

    def dispatch_assignment_announcement():
        NotificationService.broadcast_assignment_created(created, target_students)

    background_tasks.add_task(dispatch_assignment_announcement)

    created["submission_count"] = 0
    created["total_students"] = len(target_students) or 42
    created["has_submitted"] = False
    created["has_reference_file"] = bool(created.get("reference_filename"))
    return created


@app.get("/api/assignments/{assignment_id}/file")
def download_assignment_reference(assignment_id: int):
    with connect() as db:
        row = db.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Assignment not found.")
        item = dict(row)
    path_value = item.get("reference_file_path")
    if not path_value:
        raise HTTPException(404, "No reference file is attached to this assignment.")
    path = Path(path_value)
    if not path.exists():
        raise HTTPException(404, "Reference file is missing on disk.")
    return FileResponse(
        path,
        filename=item.get("reference_filename") or path.name,
        media_type="application/octet-stream",
    )


@app.put("/api/assignments/{assignment_id}")
def update_assignment(
    assignment_id: int,
    payload: AssignmentUpdate,
    current_user: Optional[dict] = Depends(get_optional_current_user),
):
    """
    Faculty edits existing assignment portal to dynamically extend or change deadlines,
    title, or target batch.
    """
    with connect() as db:
        existing = db.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Assignment portal not found.")

        current = dict(existing)
        new_title = payload.title if payload.title is not None else current["title"]
        new_subject = payload.subject if payload.subject is not None else current.get("subject", "Data Structures")
        new_batch = payload.batch_id if payload.batch_id is not None else current["batch_id"]
        new_deadline = payload.deadline if payload.deadline is not None else current["deadline"]
        new_description = payload.description if payload.description is not None else current["description"]
        stamp = now()

        db.execute(
            """UPDATE assignments SET
                title = ?, subject = ?, batch_id = ?, deadline = ?, description = ?, updated_at = ?
               WHERE id = ?""",
            (new_title, new_subject, new_batch, new_deadline, new_description, stamp, assignment_id),
        )
        updated = db.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        res = dict(updated)

        sub_count = db.execute("SELECT count(*) FROM submissions WHERE assignment_id = ?", (assignment_id,)).fetchone()[0]
        res["submission_count"] = sub_count
        res["total_students"] = 42
        return res


@app.delete("/api/assignments/{assignment_id}")
def delete_assignment(assignment_id: int):
    with connect() as db:
        db.execute("DELETE FROM submissions WHERE assignment_id = ?", (assignment_id,))
        db.execute("DELETE FROM assignment_reminder_logs WHERE assignment_id = ?", (assignment_id,))
        db.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))
    return {"status": "success", "message": f"Assignment {assignment_id} deleted."}


@app.post("/api/assignments/{assignment_id}/submit")
async def submit_assignment(
    assignment_id: int,
    file: UploadFile = File(...),
    student_id: Optional[str] = Form(None),
    current_user: Optional[dict] = Depends(get_optional_current_user),
):
    """Submit student assignment file with instant validation and disk persistence."""
    sid = student_id or (str(current_user.get("id")) if current_user else "std-001")
    return save_student_submission(assignment_id, sid, file)


@app.get("/api/assignments/{assignment_id}/submissions")
def get_submissions(assignment_id: int):
    with connect() as db:
        rows = db.execute(
            """SELECT sub.*, COALESCE(s.name, u.name, 'Student ' || sub.student_id) as student_name,
                      COALESCE(s.email, u.email, 'student@college.edu') as student_email
               FROM submissions sub
               LEFT JOIN students s ON sub.student_id = s.id
               LEFT JOIN users u ON sub.student_id = CAST(u.id AS TEXT)
               WHERE sub.assignment_id = ?
               ORDER BY sub.submitted_at DESC""",
            (assignment_id,),
        ).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/assignments/{assignment_id}/export")
def export_assignment_zip(assignment_id: int):
    zip_path, filename = create_assignment_zip_archive(assignment_id)
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=filename,
    )


# --- Attendance Tracking ---


class AttendanceCheckIn(BaseModel):
    student_id: str
    student_name: Optional[str] = None
    batch_id: Optional[str] = None
    class_id: int
    subject: Optional[str] = None


class AttendanceOverride(BaseModel):
    overrides: list[dict]  # [{student_id, status}]


@app.post("/api/attendance/check-in")
def attendance_check_in(
    payload: AttendanceCheckIn,
    current_user: Optional[dict] = Depends(get_optional_current_user),
):
    """
    Called when a student clicks 'Join Google Meet as Student'.
    Upserts their attendance record as 'Present' with the current timestamp.
    """
    stamp = now()

    # Resolve student info from token if available
    sid = payload.student_id or (str(current_user.get("id")) if current_user else None)
    if not sid:
        raise HTTPException(400, "student_id is required")

    with connect() as db:
        session = db.execute(
            "SELECT * FROM class_sessions WHERE id = ?", (payload.class_id,)
        ).fetchone()
        if not session:
            raise HTTPException(404, "Class session not found")
        session_dict = dict(session)

        # Resolve student name
        student_name = payload.student_name
        if not student_name and current_user:
            student_name = current_user.get("name")
        if not student_name:
            row = db.execute(
                "SELECT name FROM students WHERE id = ? UNION SELECT name FROM users WHERE id = ? LIMIT 1",
                (sid, sid),
            ).fetchone()
            student_name = row[0] if row else f"Student {sid}"

        # Resolve batch_id
        batch_id = payload.batch_id
        if not batch_id and current_user:
            batch_id = current_user.get("batch_id")
        if not batch_id:
            batch_id = session_dict.get("batch", "")

        subject = payload.subject or session_dict.get("subject", "")

        db.execute(
            """INSERT INTO attendance_records (student_id, student_name, batch_id, class_id, subject, status, timestamp, verified_by_faculty)
               VALUES (?, ?, ?, ?, ?, 'Present', ?, 0)
               ON CONFLICT(student_id, class_id) DO UPDATE SET
                 status = 'Present',
                 timestamp = excluded.timestamp,
                 subject = COALESCE(excluded.subject, attendance_records.subject)""",
            (sid, student_name, batch_id, payload.class_id, subject, stamp),
        )

    return {
        "status": "checked_in",
        "student_id": sid,
        "class_id": payload.class_id,
        "subject": subject,
        "timestamp": stamp,
    }


@app.get("/api/attendance/student/{student_id}")
def get_student_attendance(
    student_id: str,
    current_user: Optional[dict] = Depends(get_optional_current_user),
):
    """
    Returns subject-wise real-time attendance statistics for a given student.
    Calculates attended classes vs. total classes held and color-coded eligibility percentage.
    """
    with connect() as db:
        student = db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        batch_id = student["batch_id"] if student else None
        if not batch_id and current_user and str(current_user.get("id")) == str(student_id):
            batch_id = current_user.get("batch_id")
        if not batch_id:
            batch_id = "CS-2A"

        sessions = db.execute(
            """SELECT id, subject, batch FROM class_sessions
               WHERE batch = ? OR ? LIKE '%' || batch || '%' OR batch IS NULL""",
            (batch_id, batch_id),
        ).fetchall()

        records = db.execute(
            "SELECT * FROM attendance_records WHERE student_id = ?",
            (student_id,),
        ).fetchall()
        record_map = {r["class_id"]: dict(r) for r in records}

        curriculum_defaults = {
            "Data Structures": {"baseline_held": 18, "baseline_attended": 16},
            "Algorithms": {"baseline_held": 15, "baseline_attended": 13},
            "Database Systems": {"baseline_held": 16, "baseline_attended": 14},
            "Computer Networks": {"baseline_held": 14, "baseline_attended": 11},
            "Operating Systems": {"baseline_held": 12, "baseline_attended": 9},
        }

        subject_map = {}
        for subj, base in curriculum_defaults.items():
            subject_map[subj] = {
                "attended": base["baseline_attended"],
                "total": base["baseline_held"],
                "live_sessions": 0,
            }

        for s in sessions:
            s_dict = dict(s)
            raw = s_dict.get("subject", "General")
            clean_name = raw.split(" CS-")[0].split(" CS")[0].strip()
            if clean_name not in subject_map:
                subject_map[clean_name] = {"attended": 10, "total": 12, "live_sessions": 0}

            subject_map[clean_name]["live_sessions"] += 1
            subject_map[clean_name]["total"] += 1
            rec = record_map.get(s_dict["id"])
            if rec and rec.get("status") in ("Present", "Late"):
                subject_map[clean_name]["attended"] += 1

        for r in records:
            r_dict = dict(r)
            raw = r_dict.get("subject", "General")
            clean_name = raw.split(" CS-")[0].split(" CS")[0].strip()
            if clean_name not in subject_map:
                subject_map[clean_name] = {"attended": 0, "total": 1, "live_sessions": 1}
                if r_dict.get("status") in ("Present", "Late"):
                    subject_map[clean_name]["attended"] += 1

        subjects_out = []
        tot_att = 0
        tot_held = 0
        for subj_name, stats in subject_map.items():
            att = stats["attended"]
            tot = max(stats["total"], 1)
            pct = round((att / tot) * 100, 1)
            tot_att += att
            tot_held += tot
            subjects_out.append({
                "subject": subj_name,
                "attended": att,
                "total": tot,
                "percentage": pct,
                "status": "Eligible" if pct >= 75 else ("Warning" if pct >= 50 else "Shortage"),
            })

        subjects_out.sort(key=lambda x: x["subject"])
        overall_pct = round((tot_att / max(tot_held, 1)) * 100, 1)

        return {
            "student_id": student_id,
            "batch_id": batch_id,
            "overall_percentage": overall_pct,
            "total_attended": tot_att,
            "total_classes": tot_held,
            "subjects": subjects_out,
        }


@app.get("/api/attendance/session/{class_id}")
def get_session_roster(
    class_id: int,
    current_user: Optional[dict] = Depends(get_optional_current_user),
):
    """
    Returns the full attendance roster for a given class session.
    Students who haven't checked in are auto-filled as 'Absent'.
    """
    with connect() as db:
        session = db.execute(
            "SELECT * FROM class_sessions WHERE id = ?", (class_id,)
        ).fetchone()
        if not session:
            raise HTTPException(404, "Class session not found")
        session_dict = dict(session)
        batch = session_dict.get("batch", "")

        # All enrolled students in this batch
        enrolled = db.execute(
            """SELECT DISTINCT s.id, s.name, s.batch_id FROM students s
               WHERE (s.batch_id = ? OR ? LIKE '%' || s.batch_id || '%') AND s.active = 1""",
            (batch, batch),
        ).fetchall()

        # Existing check-ins for this session
        checked_in = db.execute(
            "SELECT * FROM attendance_records WHERE class_id = ?", (class_id,)
        ).fetchall()
        checkin_map = {row["student_id"]: dict(row) for row in checked_in}

        roster = []
        for student in enrolled:
            sid = student["id"]
            if sid in checkin_map:
                roster.append(checkin_map[sid])
            else:
                # Auto-fill Absent for non-checked-in students
                roster.append({
                    "id": None,
                    "student_id": sid,
                    "student_name": student["name"],
                    "batch_id": student["batch_id"] or batch,
                    "class_id": class_id,
                    "subject": session_dict.get("subject", ""),
                    "status": "Absent",
                    "timestamp": None,
                    "verified_by_faculty": 0,
                })

        return {
            "class_id": class_id,
            "subject": session_dict.get("subject", ""),
            "batch": batch,
            "class_date": session_dict.get("class_date"),
            "start_time": session_dict.get("start_time"),
            "faculty_name": session_dict.get("faculty_name"),
            "total_enrolled": len(enrolled),
            "present_count": sum(1 for r in roster if r["status"] == "Present"),
            "roster": roster,
        }


@app.post("/api/attendance/session/{class_id}/override")
def override_attendance(
    class_id: int,
    payload: AttendanceOverride,
    current_user: Optional[dict] = Depends(get_optional_current_user),
):
    """
    Faculty can manually toggle a student's attendance status and save the finalized roster.
    Supports statuses: 'Present', 'Absent', 'Late'.
    """
    stamp = now()
    with connect() as db:
        session = db.execute(
            "SELECT * FROM class_sessions WHERE id = ?", (class_id,)
        ).fetchone()
        if not session:
            raise HTTPException(404, "Class session not found")
        session_dict = dict(session)

        updated = []
        for item in payload.overrides:
            sid = item.get("student_id")
            new_status = item.get("status", "Absent")
            student_name = item.get("student_name", f"Student {sid}")
            batch_id = item.get("batch_id", session_dict.get("batch", ""))

            if new_status not in ("Present", "Absent", "Late"):
                new_status = "Absent"

            db.execute(
                """INSERT INTO attendance_records (student_id, student_name, batch_id, class_id, subject, status, timestamp, verified_by_faculty)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                   ON CONFLICT(student_id, class_id) DO UPDATE SET
                     status = excluded.status,
                     timestamp = excluded.timestamp,
                     verified_by_faculty = 1""",
                (sid, student_name, batch_id, class_id, session_dict.get("subject", ""), new_status, stamp),
            )
            updated.append({"student_id": sid, "status": new_status})

    return {
        "status": "success",
        "class_id": class_id,
        "overrides_applied": len(updated),
        "updated": updated,
    }


@app.get("/api/attendance/session/{class_id}/export")
def export_attendance_csv(class_id: int):
    """
    Generates and downloads a formatted CSV attendance report for the class session.
    Columns: Batch, Subject, Student Name, Status, Timestamp.
    """
    import csv
    import io
    import tempfile

    with connect() as db:
        session = db.execute(
            "SELECT * FROM class_sessions WHERE id = ?", (class_id,)
        ).fetchone()
        if not session:
            raise HTTPException(404, "Class session not found")
        session_dict = dict(session)
        batch = session_dict.get("batch", "")

        enrolled = db.execute(
            """SELECT DISTINCT s.id, s.name, s.batch_id FROM students s
               WHERE (s.batch_id = ? OR ? LIKE '%' || s.batch_id || '%') AND s.active = 1""",
            (batch, batch),
        ).fetchall()

        checked_in = db.execute(
            "SELECT * FROM attendance_records WHERE class_id = ?", (class_id,)
        ).fetchall()
        checkin_map = {row["student_id"]: dict(row) for row in checked_in}

        rows = []
        for student in enrolled:
            sid = student["id"]
            if sid in checkin_map:
                rec = checkin_map[sid]
                rows.append({
                    "Batch": rec["batch_id"],
                    "Subject": rec["subject"],
                    "Student ID": sid,
                    "Student Name": rec["student_name"],
                    "Status": rec["status"],
                    "Timestamp": rec["timestamp"] or "",
                    "Verified by Faculty": "Yes" if rec["verified_by_faculty"] else "No",
                })
            else:
                rows.append({
                    "Batch": student["batch_id"] or batch,
                    "Subject": session_dict.get("subject", ""),
                    "Student ID": sid,
                    "Student Name": student["name"],
                    "Status": "Absent",
                    "Timestamp": "",
                    "Verified by Faculty": "No",
                })

    # Write CSV to a temp file
    output = io.StringIO()
    fieldnames = ["Batch", "Subject", "Student ID", "Student Name", "Status", "Timestamp", "Verified by Faculty"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    csv_content = output.getvalue()

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w", encoding="utf-8")
    tmp.write(csv_content)
    tmp.close()

    date_str = session_dict.get("class_date", "session")
    subj = session_dict.get("subject", "class").replace(" ", "_")
    filename = f"attendance_{subj}_{date_str}_{class_id}.csv"

    return FileResponse(
        path=tmp.name,
        media_type="text/csv",
        filename=filename,
    )


def _clean_subject_name(raw: Optional[str]) -> str:
    if not raw:
        return "General"
    cleaned = re.sub(
        r"\s+(CS-\d[A-Z0-9]*|[A-Z]{2,3}-\d[A-Z0-9]*)$",
        "",
        str(raw).strip(),
        flags=re.IGNORECASE,
    ).strip()
    return cleaned or str(raw).strip()


@app.get("/api/faculty/attendance/summary")
def faculty_attendance_summary(
    current_user: Optional[dict] = Depends(get_optional_current_user),
):
    """
    Faculty-wide attendance analytics grouped by subject.
    Returns total classes conducted and average student attendance percentage per subject.
    """
    with connect() as db:
        sessions = [dict(r) for r in db.execute("SELECT * FROM class_sessions").fetchall()]
        students = [
            dict(r)
            for r in db.execute(
                "SELECT id, name, batch_id FROM students WHERE active = 1"
            ).fetchall()
        ]
        records = [
            dict(r)
            for r in db.execute(
                "SELECT class_id, status, student_id FROM attendance_records"
            ).fetchall()
        ]

    records_by_class: dict = {}
    for rec in records:
        key = rec.get("class_id")
        try:
            key = int(key)
        except (TypeError, ValueError):
            pass
        records_by_class.setdefault(key, []).append(rec)

    def enrolled_for_batch(batch: Optional[str]) -> list:
        if not batch:
            return students
        matched = [
            s
            for s in students
            if s.get("batch_id") == batch
            or (s.get("batch_id") and str(batch).find(str(s.get("batch_id"))) >= 0)
            or (s.get("batch_id") and str(s.get("batch_id")).find(str(batch)) >= 0)
        ]
        return matched or students

    grouped: dict = {}
    for session in sessions:
        subject = _clean_subject_name(session.get("subject"))
        batch = session.get("batch") or ""
        class_id = session.get("id")
        enrolled = enrolled_for_batch(batch)
        class_records = records_by_class.get(class_id) or records_by_class.get(str(class_id)) or []
        present = sum(1 for r in class_records if r.get("status") in ("Present", "Late"))
        denominator = max(len(enrolled), 1)
        session_pct = round((present / denominator) * 100, 1)

        bucket = grouped.setdefault(
            subject,
            {
                "subject": subject,
                "total_classes_conducted": 0,
                "pct_sum": 0.0,
                "total_present": 0,
                "total_enrolled_seats": 0,
                "batches": set(),
            },
        )
        bucket["total_classes_conducted"] += 1
        bucket["pct_sum"] += session_pct
        bucket["total_present"] += present
        bucket["total_enrolled_seats"] += len(enrolled)
        if batch:
            bucket["batches"].add(batch)

    subjects_out = []
    for item in grouped.values():
        conducted = max(item["total_classes_conducted"], 1)
        avg_pct = round(item["pct_sum"] / conducted, 1)
        subjects_out.append(
            {
                "subject": item["subject"],
                "total_classes_conducted": item["total_classes_conducted"],
                "average_attendance_percentage": avg_pct,
                "total_present": item["total_present"],
                "total_enrolled_seats": item["total_enrolled_seats"],
                "batches": sorted(item["batches"]),
                "status": "Strong" if avg_pct >= 75 else ("Watch" if avg_pct >= 50 else "At Risk"),
            }
        )
    subjects_out.sort(key=lambda x: x["subject"])

    total_classes = len(sessions)
    overall_avg = (
        round(sum(s["average_attendance_percentage"] for s in subjects_out) / len(subjects_out), 1)
        if subjects_out
        else 0.0
    )

    return {
        "total_classes_conducted": total_classes,
        "overall_average_percentage": overall_avg,
        "subject_count": len(subjects_out),
        "generated_at": now(),
        "subjects": subjects_out,
    }


# --- Reminders & Notifications Automation ---


@app.post("/api/reminders/trigger")
def trigger_reminders():
    """Manual or automated trigger for scheduled deadline reminders."""
    sent_count = check_and_send_assignment_reminders()
    return {
        "status": "success",
        "reminders_dispatched": sent_count,
        "detail": f"Evaluated batches and dispatched {sent_count} deadline reminders.",
    }


# --- Batch & Directory Info ---


@app.get("/api/batches")
def get_batches():
    with connect() as db:
        rows = db.execute(
            """SELECT batch_id as name, count(*) as learner_count
               FROM students
               WHERE active = 1 AND batch_id IS NOT NULL
               GROUP BY batch_id"""
        ).fetchall()
        batches = [dict(r) for r in rows]
        if not batches:
            batches = [
                {"name": "CS-2A", "learner_count": 42, "subject": "Data Structures"},
                {"name": "CS-1B", "learner_count": 36, "subject": "Algorithms"},
            ]
        return batches


@app.get("/api/people")
def get_people():
    with connect() as db:
        faculty = [dict(r) for r in db.execute("SELECT * FROM faculty WHERE active = 1").fetchall()]
        return faculty


class ThreadCreate(BaseModel):
    title: str
    body: Optional[str] = None
    scope_type: str = "public"  # public | batch | private
    batch_id: Optional[str] = None
    subject: Optional[str] = None
    recipient_faculty_id: Optional[int] = None


class ThreadMessageCreate(BaseModel):
    body: str


def _resolve_faculty_record(current_user: Optional[dict]) -> Optional[dict]:
    if not current_user:
        return None
    with connect() as db:
        if current_user.get("email"):
            row = db.execute(
                "SELECT * FROM faculty WHERE LOWER(email) = LOWER(?)",
                (current_user["email"],),
            ).fetchone()
            if row:
                return dict(row)
        try:
            fid = int(current_user.get("id"))
        except (TypeError, ValueError):
            return None
        row = db.execute("SELECT * FROM faculty WHERE id = ?", (fid,)).fetchone()
        return dict(row) if row else None


def _serialize_thread(row, message_count: int = 0, faculty_name: Optional[str] = None) -> dict:
    item = dict(row)
    item["message_count"] = message_count
    item["reply_count"] = max(message_count, 0)
    if faculty_name:
        item["recipient_faculty_name"] = faculty_name
    return item


def _thread_is_visible(thread: dict, current_user: Optional[dict], faculty_rec: Optional[dict]) -> bool:
    scope = str(thread.get("scope_type") or "public").lower()
    if scope == "public":
        return True
    if not current_user:
        return scope == "public"
    role = str(current_user.get("role") or "").upper()
    uid = str(current_user.get("id") or "")
    if scope == "batch":
        if role == "FACULTY":
            return True
        user_batch = str(current_user.get("batch_id") or "")
        thread_batch = str(thread.get("batch_id") or "")
        if not thread_batch:
            return True
        return user_batch == thread_batch or thread_batch in user_batch or user_batch in thread_batch
    if scope == "private":
        author_id = str(thread.get("author_id") or "")
        recip = thread.get("recipient_faculty_id")
        if uid and uid == author_id:
            return True
        if faculty_rec and recip is not None and int(faculty_rec["id"]) == int(recip):
            return True
        return False
    return False


def _dispatch_thread_emails(thread: dict, poster_name: str, poster_role: str, preview: str):
    scope = str(thread.get("scope_type") or "public").lower()
    if scope == "public":
        return
    if scope == "private" and str(poster_role).upper() == "STUDENT":
        fac_id = thread.get("recipient_faculty_id")
        if not fac_id:
            return
        with connect() as db:
            fac = db.execute("SELECT email, full_name FROM faculty WHERE id = ?", (fac_id,)).fetchone()
        if fac and fac["email"]:
            NotificationService.notify_faculty_direct_message(fac["email"], thread, poster_name, preview)
        return
    if scope == "batch" and str(poster_role).upper() == "FACULTY":
        recipients = get_batch_student_recipients(thread.get("batch_id") or "")
        subject = thread.get("subject")
        if subject:
            extra = get_notes_student_recipients(subject, thread.get("batch_id"))
            seen = {r.get("email") for r in recipients}
            for r in extra:
                if r.get("email") not in seen:
                    recipients.append(r)
                    seen.add(r.get("email"))
        NotificationService.notify_batch_thread_announcement(recipients, thread, poster_name, preview)


@app.get("/api/threads")
def list_threads(
    scope_type: Optional[str] = None,
    current_user: Optional[dict] = Depends(get_optional_current_user),
):
    faculty_rec = _resolve_faculty_record(current_user)
    with connect() as db:
        rows = db.execute("SELECT * FROM threads ORDER BY updated_at DESC, id DESC").fetchall()
        faculty_names = {
            r["id"]: r["full_name"]
            for r in db.execute("SELECT id, full_name FROM faculty WHERE active = 1").fetchall()
        }
        out = []
        for row in rows:
            item = dict(row)
            if scope_type and str(item.get("scope_type") or "").lower() != scope_type.lower():
                continue
            if not _thread_is_visible(item, current_user, faculty_rec):
                continue
            count = db.execute(
                "SELECT count(*) FROM thread_messages WHERE thread_id = ?",
                (item["id"],),
            ).fetchone()[0]
            recip_id = item.get("recipient_faculty_id")
            out.append(
                _serialize_thread(
                    item,
                    count,
                    faculty_names.get(recip_id) if recip_id else None,
                )
            )
        return out


@app.post("/api/threads")
def create_thread(
    payload: ThreadCreate,
    background_tasks: BackgroundTasks,
    current_user: Optional[dict] = Depends(get_optional_current_user),
):
    scope = str(payload.scope_type or "public").lower()
    if scope not in ("public", "batch", "private"):
        raise HTTPException(400, "scope_type must be public, batch, or private")
    if scope == "batch" and not payload.batch_id:
        raise HTTPException(400, "batch_id is required for batch-scoped threads")
    if scope == "private" and not payload.recipient_faculty_id:
        raise HTTPException(400, "recipient_faculty_id is required for private faculty DMs")

    author_id = str(current_user.get("id")) if current_user else None
    author_name = (current_user.get("name") if current_user else None) or "Member"
    author_role = str(current_user.get("role") or "STUDENT").upper() if current_user else "STUDENT"
    stamp = now()
    with connect() as db:
        cursor = db.execute(
            """INSERT INTO threads (
                title, body, scope_type, batch_id, subject, recipient_faculty_id,
                author_id, author_name, author_role, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                payload.title.strip(),
                (payload.body or "").strip() or None,
                scope,
                payload.batch_id if scope == "batch" else None,
                payload.subject if scope == "batch" else None,
                payload.recipient_faculty_id if scope == "private" else None,
                author_id,
                author_name,
                author_role,
                stamp,
                stamp,
            ),
        )
        thread_id = cursor.lastrowid
        row = db.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
        created = dict(row)
        fac_name = None
        if created.get("recipient_faculty_id"):
            fac = db.execute(
                "SELECT full_name FROM faculty WHERE id = ?",
                (created["recipient_faculty_id"],),
            ).fetchone()
            fac_name = fac["full_name"] if fac else None

    preview = (payload.body or payload.title or "").strip()
    background_tasks.add_task(_dispatch_thread_emails, created, author_name, author_role, preview)
    return _serialize_thread(created, 0, fac_name)


@app.get("/api/threads/{thread_id}")
def get_thread(
    thread_id: int,
    current_user: Optional[dict] = Depends(get_optional_current_user),
):
    faculty_rec = _resolve_faculty_record(current_user)
    with connect() as db:
        row = db.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Thread not found")
        thread = dict(row)
        if not _thread_is_visible(thread, current_user, faculty_rec):
            raise HTTPException(403, "You do not have access to this thread")
        messages = [
            dict(m)
            for m in db.execute(
                "SELECT * FROM thread_messages WHERE thread_id = ? ORDER BY created_at ASC, id ASC",
                (thread_id,),
            ).fetchall()
        ]
        fac_name = None
        if thread.get("recipient_faculty_id"):
            fac = db.execute(
                "SELECT full_name FROM faculty WHERE id = ?",
                (thread["recipient_faculty_id"],),
            ).fetchone()
            fac_name = fac["full_name"] if fac else None
        result = _serialize_thread(thread, len(messages), fac_name)
        result["messages"] = messages
        return result


@app.post("/api/threads/{thread_id}/messages")
def post_thread_message(
    thread_id: int,
    payload: ThreadMessageCreate,
    background_tasks: BackgroundTasks,
    current_user: Optional[dict] = Depends(get_optional_current_user),
):
    body = (payload.body or "").strip()
    if not body:
        raise HTTPException(400, "Message body is required")
    faculty_rec = _resolve_faculty_record(current_user)
    author_id = str(current_user.get("id")) if current_user else None
    author_name = (current_user.get("name") if current_user else None) or "Member"
    author_role = str(current_user.get("role") or "STUDENT").upper() if current_user else "STUDENT"
    stamp = now()
    with connect() as db:
        row = db.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Thread not found")
        thread = dict(row)
        if not _thread_is_visible(thread, current_user, faculty_rec):
            raise HTTPException(403, "You do not have access to this thread")
        cursor = db.execute(
            """INSERT INTO thread_messages (thread_id, author_id, author_name, author_role, body, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (thread_id, author_id, author_name, author_role, body, stamp),
        )
        db.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (stamp, thread_id))
        msg_id = cursor.lastrowid
        message = dict(db.execute("SELECT * FROM thread_messages WHERE id = ?", (msg_id,)).fetchone())

    background_tasks.add_task(_dispatch_thread_emails, thread, author_name, author_role, body)
    return message


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "mode": APP_MODE,
        "google_meet_creation_allowed": MEET_CREATION_ALLOWED,
        "email_delivery_enabled": EMAIL_DELIVERY_ENABLED,
        "timestamp": now(),
    }


# --- Static Frontend Serving ---

frontend_dir = ROOT / "frontend"
if not frontend_dir.exists():
    frontend_dir.mkdir(parents=True, exist_ok=True)

app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")