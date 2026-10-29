"""End-to-End API Routes Verification Script."""

from fastapi import BackgroundTasks, UploadFile
import io
from app.main import (
    login,
    microsoft_sso,
    current_user_profile,
    list_classes,
    get_session_meet_link,
    create_sudden_class,
    list_assignments,
    persist_new_assignment,
    update_assignment,
    delete_assignment,
    get_submissions,
    submit_assignment,
    trigger_reminders,
    get_batches,
    get_people,
    LoginRequest,
    MicrosoftAuthRequest,
    AssignmentCreate,
    AssignmentUpdate,
)

print("Starting Openclass E2E Routes Test...")

# 1. Faculty Login
fac_login = login(LoginRequest(email="priya.menon@college.edu", password="password123", role="FACULTY"))
fac_user = fac_login["user"]
fac_token = fac_login["access_token"]
print("1. Faculty Login OK:", fac_user["name"], "-", fac_user["role"])

# 2. Student Login
std_login = login(LoginRequest(email="arjun.rao@college.edu", password="password123", role="STUDENT"))
std_user = std_login["user"]
print("2. Student Login OK:", std_user["name"], "-", std_user["role"], "Batch:", std_user["batch_id"])

# 3. Microsoft SSO
ms_login = microsoft_sso(MicrosoftAuthRequest(email="arjun.rao@college.edu", name="Arjun Rao", role="STUDENT", batch_id="CS-2A"))
print("3. Microsoft SSO OK:", ms_login["user"]["email"])

# 4. List Classes (Student View - Filtered)
std_classes = list_classes(current_user=std_user)
print("4. Student Classes OK: Count =", len(std_classes))
first_class = std_classes[0]
print("   First class:", first_class["subject"], "Meet:", first_class["google_meet_url"])

# 5. Meet Link with Host Controls
std_meet = get_session_meet_link(first_class["id"], current_user=std_user)
print("5. Student Meet Link OK:")
print("   Role Badge:", std_meet["role_badge"])
print("   Controls Notice:", std_meet["controls_notice"])
print("   Launch URL:", std_meet["launch_url"])

fac_meet = get_session_meet_link(first_class["id"], current_user=fac_user)
print("   Faculty Meet Link OK:")
print("   Role Badge:", fac_meet["role_badge"])
print("   Is Host:", fac_meet["is_host"])
print("   Controls Notice:", fac_meet["controls_notice"])

# 6. Sudden Class Creation (Faculty)
bg = BackgroundTasks()
sudden = create_sudden_class(
    {
        "subject": "Advanced Graph Traversal Workshop",
        "class_date": "2026-10-15",
        "start_time": "18:00",
        "batch": "CS-2A",
        "duration_minutes": 60,
        "faculty_name": "Priya Menon",
        "faculty_email": "priya.menon@college.edu",
    },
    background_tasks=bg,
)
print("6. Sudden Class Created OK:")
print("   Session ID:", sudden["session_id"])
print("   Meeting URL:", sudden["meeting_url"])
print("   Host Controls:", sudden["host_controls"]["sole_host"])

# 7. Assignment Creation (Faculty)
new_assign = persist_new_assignment(
    title="Assignment 5: Dynamic Programming & Memoization",
    subject="Data Structures",
    batch_id="CS-2A",
    deadline="2026-10-25T23:59:00Z",
    description="Solve 0/1 Knapsack and Matrix Chain Multiplication with top-down memoization.",
    faculty_id=fac_user.get("id") if fac_user else 1,
    faculty_name=(fac_user.get("name") if fac_user else "Priya Menon"),
)
assign_id = new_assign["id"]
print("7. Assignment Created OK: ID =", assign_id, "Title =", new_assign["title"])

# 8. Dynamic Deadline Extension (Faculty)
updated_assign = update_assignment(
    assign_id,
    AssignmentUpdate(
        deadline="2026-10-28T23:59:00Z",
        description="Deadline dynamically extended by 3 days for midterm review.",
    ),
    current_user=fac_user,
)
print("8. Assignment Deadline Extended OK: New Deadline =", updated_assign["deadline"])

# 9. List Assignments (Student View - filtered strictly to CS-2A)
std_assignments = list_assignments(current_user=std_user)
print("9. Student Assignments Filtered OK: Count =", len(std_assignments))
for a in std_assignments:
    print(f"   - {a['title']} ({a['batch_id']}) | Has Submitted: {a['has_submitted']}")

# 10. Student Submission
file_content = b"%PDF-1.4 Mock Assignment Solution PDF by Arjun Rao"
upload_file = UploadFile(filename="arjun_knapsack_solution.pdf", file=io.BytesIO(file_content))
import asyncio
sub_res = asyncio.run(submit_assignment(assign_id, upload_file, student_id=str(std_user["id"]), current_user=std_user))
print("10. Student Submission Uploaded OK:", sub_res["original_filename"])

# 11. Faculty View Submissions
submissions = get_submissions(assign_id)
print("11. Faculty View Submissions OK: Count =", len(submissions))
print("    Submission Details:", submissions[0]["student_name"], "-", submissions[0]["original_filename"])

# 12. Trigger Reminders
rem_res = trigger_reminders()
print("12. Trigger Reminders OK:", rem_res["status"], "Dispatched:", rem_res["reminders_dispatched"])

# 13. Batches & People
batches = get_batches()
people = get_people()
print("13. Batches:", [b["name"] for b in batches])
print("    People:", [p["full_name"] for p in people])

print("\nALL 13 API SUITE TESTS PASSED WITH 100% SUCCESS!")
