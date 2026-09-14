import logging
from datetime import datetime, timezone

from ..db import connect, now
from ..gmail_sender import send_email

logger = logging.getLogger(__name__)

def check_and_send_assignment_reminders():
    # 1. Fetch Google credentials from database
    with connect() as db:
        row = db.execute("SELECT credentials_json FROM google_credentials WHERE id=1").fetchone()
        if not row:
            logger.warning("Google account not connected. Cannot send assignment reminders.")
            return
        credentials_json = row["credentials_json"]

    # 2. Fetch all assignments
    with connect() as db:
        assignments = [dict(r) for r in db.execute("SELECT * FROM assignments").fetchall()]

    for assignment in assignments:
        deadline_str = assignment["deadline"]
        try:
            deadline_dt = datetime.fromisoformat(deadline_str)
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid deadline format for assignment {assignment['id']}: {deadline_str}. Error: {e}")
            continue

        if deadline_dt.tzinfo is None:
            deadline_dt = deadline_dt.replace(tzinfo=timezone.utc)

        now_dt = datetime.now(timezone.utc)
        
        # Calculate days_remaining = (deadline - now).days
        days_remaining = (deadline_dt - now_dt).days

        # If days_remaining matches 10, 7, 5, 3, 2, or 1 days
        if days_remaining not in [10, 7, 5, 3, 2, 1]:
            continue

        batch_id = assignment["batch_id"]
        assignment_id = assignment["id"]
        title = assignment["title"]

        # Fetch all students in the batch who have NOT yet submitted this assignment
        with connect() as db:
            students = [
                dict(r) for r in db.execute(
                    """
                    SELECT s.id, s.name, s.email FROM students s
                    WHERE s.batch_id = ? AND s.active = 1
                    AND s.id NOT IN (
                        SELECT student_id FROM submissions WHERE assignment_id = ?
                    )
                    """,
                    (batch_id, assignment_id)
                ).fetchall()
            ]

        for student in students:
            student_id = student["id"]
            student_email = student["email"]
            student_name = student["name"]

            if not student_email:
                continue

            # Check if reminder has already been sent to this student for this assignment and days_remaining
            with connect() as db:
                reminder_logged = db.execute(
                    """
                    SELECT 1 FROM assignment_reminder_logs
                    WHERE assignment_id = ? AND student_id = ? AND days_remaining = ?
                    """,
                    (assignment_id, student_id, days_remaining)
                ).fetchone()

            if reminder_logged:
                continue

            subject = f"Reminder: Submission due for {title} ({days_remaining} day{'s' if days_remaining > 1 else ''} left)"
            submission_link = f"http://localhost:8000/api/assignments/{assignment_id}/submit"
            
            body = (
                f"Hello {student_name},\n\n"
                f"This is a reminder that the assignment '{title}' is pending your submission.\n\n"
                f"Assignment Details:\n"
                f"- Title: {title}\n"
                f"- Days Remaining: {days_remaining}\n"
                f"- Deadline: {deadline_str}\n\n"
                f"You can upload your submission directly here:\n"
                f"{submission_link}\n\n"
                f"Thank you,\n"
                f"ClassroomFlow System"
            )

            try:
                msg_id = send_email(credentials_json, student_email, subject, body)
                stamp = now()
                with connect() as db:
                    db.execute(
                        """
                        INSERT INTO assignment_reminder_logs (assignment_id, student_id, days_remaining, sent_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (assignment_id, student_id, days_remaining, stamp)
                    )
                    db.execute(
                        """
                        INSERT INTO delivery_log(action, status, detail, created_at)
                        VALUES (?, 'sent', ?, ?)
                        """,
                        (f"assignment_reminder_{days_remaining}d", f"Sent to {student_email} (Msg ID: {msg_id})", stamp)
                    )
                logger.info(f"Sent reminder for assignment {assignment_id} to student {student_email} (days left: {days_remaining})")
            except Exception as e:  # noqa: BLE001
                logger.error(f"Failed to send reminder to student {student_email}: {e}")
