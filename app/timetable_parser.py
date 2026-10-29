import re
from dataclasses import dataclass

from openpyxl import load_workbook

TIME=re.compile(r"^\s*(\d{1,2}(?::\d{2})?)\s*(?:-|–|to)\s*(\d{1,2}(?::\d{2})?)\s*$",re.IGNORECASE)
ENTRY=re.compile(r"^\s*\d+\)\s*(.+?)\s*$")
BATCH=re.compile(r"\s*-\s*Batch\s*(\d+)\s*$",re.IGNORECASE)
DAYS=["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]
@dataclass
class ParsedClass: weekday:str; start_time:str; end_time:str; subject:str; batch:str|None; faculty_name:str|None
def clock(value): value=value.strip(); return value if ":" in value else f"{value}:00"
def parse_timetable(path):
    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb.active
    if ws is None:
        return []
    classes = []
    for row in ws.iter_rows(values_only=True):
        time_col = next((i for i, v in enumerate(row[:2]) if TIME.match(str(v or '').replace('.', ':').strip())), None)
        if time_col is None:
            continue
        match = TIME.match(str(row[time_col]).replace('.', ':').strip())
        if match is None:
            continue
        for day, cell in zip(DAYS, row[time_col+1:time_col+7]):
            lines = [x.strip() for x in str(cell or '').splitlines() if x.strip()]
            for i, line in enumerate(lines):
                entry = ENTRY.match(line)
                if not entry:
                    continue
                course = entry.group(1)
                batch = BATCH.search(course)
                faculty = lines[i+1] if i+1 < len(lines) and not ENTRY.match(lines[i+1]) else None
                
                start_time = clock(match.group(1))
                end_time = clock(match.group(2))
                subject_name = BATCH.sub('', course).strip()
                batch_name = f"Batch {batch.group(1)}" if batch is not None else None
                
                classes.append(ParsedClass(
                    weekday=day,
                    start_time=start_time,
                    end_time=end_time,
                    subject=subject_name,
                    batch=batch_name,
                    faculty_name=faculty
                ))
    return classes


STUDENT_SHEET_HINTS = ("student", "roster", "testng", "learners")
NAME_HEADERS = {"name", "student name", "full name", "student", "learner"}
EMAIL_HEADERS = {"email", "e-mail", "mail", "student email"}
BATCH_HEADERS = {"batch", "batch name", "batch id", "class", "section", "division", "group"}
PHONE_HEADERS = {"phone", "mobile", "contact", "phone number"}
ROLL_HEADERS = {"roll", "roll no", "roll number", "id", "student id", "enrolment", "enrollment"}


def _header_key(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()


def _map_student_headers(cells) -> dict:
    mapping = {}
    for idx, cell in enumerate(cells):
        key = _header_key(cell)
        if not key:
            continue
        if key in NAME_HEADERS or key.endswith(" name"):
            mapping.setdefault("name", idx)
        elif key in EMAIL_HEADERS:
            mapping.setdefault("email", idx)
        elif key in BATCH_HEADERS or "batch" in key:
            mapping.setdefault("batch", idx)
        elif key in PHONE_HEADERS:
            mapping.setdefault("phone", idx)
        elif key in ROLL_HEADERS:
            mapping.setdefault("roll_no", idx)
    return mapping if "name" in mapping or "email" in mapping else {}


def parse_student_roster(path) -> list[dict]:
    """Read student rows from sheets such as Students-Testng in the uploaded workbook."""
    wb = load_workbook(path, data_only=True, read_only=True)
    people = []
    seen = set()
    sheets = list(wb.worksheets)
    preferred = [
        ws for ws in sheets
        if any(hint in (ws.title or "").lower() for hint in STUDENT_SHEET_HINTS)
    ]
    ordered = preferred + [ws for ws in sheets if ws not in preferred]
    for ws in ordered:
        title = (ws.title or "").lower()
        if preferred and ws not in preferred and "time" in title:
            continue
        header_map = {}
        for row in ws.iter_rows(values_only=True):
            cells = list(row or [])
            if not header_map:
                header_map = _map_student_headers(cells)
                continue
            def cell(field):
                idx = header_map.get(field)
                if idx is None or idx >= len(cells):
                    return ""
                value = cells[idx]
                return str(value).strip() if value is not None else ""
            name = cell("name")
            email = cell("email").lower()
            batch = cell("batch")
            if not name and not email:
                continue
            identity = email or name.lower()
            if identity in seen:
                continue
            seen.add(identity)
            people.append({
                "name": name,
                "email": email,
                "batch": batch,
                "phone": cell("phone"),
                "roll_no": cell("roll_no"),
                "sheet": ws.title,
            })
        if preferred and ws in preferred and people:
            break
    return people
