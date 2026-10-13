import logging
from datetime import datetime, timezone
from typing import List, Optional

from ..db import connect, now
from .notification import NotificationService

logger = logging.getLogger("openclass.reminders")


def check_and_send_assignment_reminders() -> int:
    """
    Scans all assignments, identifies upcoming deadlines for specific batches,
    and sends automated reminder emails to enrolled students who have not submitted yet.
    """
    total_reminders_sent = 0
    with connect() as db:
        assignments = [dict(r) for r in db.execute("SELECT * FROM assignments").fetchall()]

    now_dt = datetime.now(timezone.utc)

    for assignment in assignments:
        deadline_str = assignment.get("deadline")
        if not deadline_str:
            continue

        try:
            deadline_clean = deadline_str.replace("Z", "+00:00")
            deadline_dt = datetime.fromisoformat(deadline_clean)
            if deadline_dt.tzinfo is None:
                deadline_dt = deadline_dt.replace(tzinfo=timezone.utc)
        except Exception as e:
            logger.error(f"Invalid deadline format for assignment {assignment.get('id')}: {deadline_str}. {e}")
            continue

        diff = deadline_dt - now_dt
        total_hours = diff.total_seconds() / 3600.0

        if total_hours <= 0:
            # Deadline has passed
            continue

        # Determine reminder tier: 2h, 24h, or multi-day
        reminder_tier = None
        if total_hours <= 2.5 and total_hours > 0:
            reminder_tier = "2h"
        elif total_hours <= 25.0 and total_hours > 20.0:
            reminder_tier = "24h"
        elif total_hours <= 73.0 and total_hours > 68.0:
            reminder_tier = "3d"
        elif total_hours <= 169.0 and total_hours > 164.0:
            reminder_tier = "7d"

        if not reminder_tier:
            continue

        batch_id = assignment.get("batch_id")
        assignment_id = assignment.get("id")

        # Fetch enrolled students in this specific batch who have NOT yet submitted
        with connect() as db:
            students = [
                dict(r)
                for r in db.execute(
                    """
                    SELECT s.id, s.name, s.email, s.phone FROM students s
                    WHERE (s.batch_id = ? OR ? LIKE '%' || s.batch_id || '%') AND s.active = 1
                    AND s.id NOT IN (
                        SELECT student_id FROM submissions WHERE assignment_id = ?
                    )
                    """,
                    (batch_id, batch_id, assignment_id),
                ).fetchall()
            ]

        for student in students:
            student_id = str(student.get("id"))
            student_email = student.get("email")

            if not student_email:
                continue

            # Check if reminder already sent for this assignment + student + reminder_tier
            with connect() as db:
                logged = db.execute(
                    """
                    SELECT 1 FROM assignment_reminder_logs
                    WHERE assignment_id = ? AND student_id = ? AND reminder_type = ?
                    """,
                    (assignment_id, student_id, reminder_tier),
                ).fetchone()

            if logged:
                continue

            # Send reminder email
            sent = NotificationService.send_assignment_reminder(assignment, student, reminder_tier)
            if sent:
                total_reminders_sent += 1
                logger.info(f"Dispatched {reminder_tier} reminder for assignment {assignment_id} to {student_email}")

    return total_reminders_sent
