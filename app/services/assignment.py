import io
import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Optional, Tuple
from fastapi import HTTPException, UploadFile

from ..config import UPLOAD_DIR
from ..db import connect, now

def sanitize_filename(filename: str) -> str:
    # Remove any path traversal or unsafe characters
    clean = Path(filename).name
    clean = re.sub(r"[^a-zA-Z0-9_.-]", "_", clean)
    return clean or "submission"

def save_student_submission(assignment_id: int, student_id: str, file: UploadFile) -> dict:
    with connect() as db:
        assignment = db.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found")
        student = db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        if not student:
            # Check user table
            user = db.execute("SELECT * FROM users WHERE id = ?", (student_id,)).fetchone()
            if not user:
                raise HTTPException(status_code=404, detail="Student not found")

    original_name = file.filename or "submission.pdf"
    clean_name = sanitize_filename(original_name)
    ext = Path(clean_name).suffix.lower()
    
    # Target directory: /uploads/assignments/{assignment_id}/
    target_dir = UPLOAD_DIR / "assignments" / str(assignment_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    # Standardized file naming: {student_id}_{assignment_id}_{clean_name}
    standard_filename = f"std_{student_id}_assign_{assignment_id}_{clean_name}"
    target_path = target_dir / standard_filename

    with target_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    stamp = now()
    with connect() as db:
        cursor = db.execute(
            """INSERT INTO submissions (assignment_id, student_id, file_path, original_filename, submitted_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(assignment_id, student_id) DO UPDATE SET
               file_path=excluded.file_path, original_filename=excluded.original_filename, submitted_at=excluded.submitted_at""",
            (assignment_id, str(student_id), str(target_path), original_name, stamp)
        )
        row = db.execute(
            "SELECT * FROM submissions WHERE assignment_id = ? AND student_id = ?",
            (assignment_id, str(student_id))
        ).fetchone()
        return dict(row)

def create_assignment_zip_archive(assignment_id: int) -> Tuple[str, str]:
    """
    Compresses all student submissions for a given assignment into a .zip file.
    Returns (zip_file_path, zip_filename).
    """
    with connect() as db:
        assignment = db.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found")
        
        submissions = db.execute("SELECT * FROM submissions WHERE assignment_id = ?", (assignment_id,)).fetchall()

    export_dir = UPLOAD_DIR / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    
    safe_title = sanitize_filename(assignment["title"])
    zip_filename = f"assignment_{assignment_id}_{safe_title}_submissions.zip"
    zip_path = export_dir / zip_filename

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        if not submissions:
            # Write a README inside zip
            zipf.writestr("README.txt", f"No student submissions found for Assignment {assignment_id}: {assignment['title']}.")
        else:
            for sub in submissions:
                file_path = Path(sub["file_path"])
                if file_path.exists():
                    arcname = f"student_{sub['student_id']}_{file_path.name}"
                    zipf.write(file_path, arcname=arcname)
                else:
                    zipf.writestr(f"student_{sub['student_id']}_MISSING.txt", f"Original file {sub['original_filename']} not found on disk.")

    return str(zip_path), zip_filename
