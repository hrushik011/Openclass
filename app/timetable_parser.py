import re
from dataclasses import dataclass

from openpyxl import load_workbook

TIME = re.compile(r'(\d{1,2}[:\.]\d{2})\s*[-–—to]+\s*(\d{1,2}[:\.]\d{2})', re.IGNORECASE)
ENTRY=re.compile(r"^\s*\d+\)\s*(.+?)\s*$")
BATCH=re.compile(r"(?:-|–)?\s*(?:Batch|B)\s*(\d+)(?:\s*of\s*\d+)?\s*$",re.IGNORECASE)
DAYS=["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]

@dataclass
class ParsedClass: weekday:str; start_time:str; end_time:str; subject:str; batch:str|None; faculty_name:str|None
def clock(hour, minute="00"):
    """Convert hour[+minute] to 24-hour HH:MM string.

    Accepts either:
    * Two separate args: clock('1', '30') or clock(1, 30)
    * One colon-joined string: clock('1:30') – e.g. from a 2-group regex match

    Hours 1-6 are treated as PM (college schedule heuristic):
      1→13, 2→14, 3→15, 4→16, 5→17, 6→18.
    Hours 7-12 and 13-23 pass through unchanged.
    """
    # Unpack 'H:MM' or 'HH:MM' when passed as a single string
    hour_str = str(hour).strip()
    if ":" in hour_str:
        parts = hour_str.split(":", 1)
        hour_str = parts[0]
        minute = parts[1]
    try:
        hour_n = int(hour_str)
        minute_n = int(str(minute).strip())
    except ValueError:
        # Last-resort: return whatever we received
        return f"{hour}:{minute}"
    if 1 <= hour_n <= 6:
        hour_n += 12
    return f"{hour_n:02d}:{minute_n:02d}"


def _row_time_range(row):
    """Scan the first 4 cells of a timetable row for a time range.

    Returns (start_time, end_time, col_index_of_match) or None.
    """
    cells = list(row or [])
    blob_parts = []
    for idx, value in enumerate(cells[:4]):
        text = str(value or "").strip().replace("\u00a0", " ").replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")
        blob_parts.append(text)
        # Normalise dots to colons so '9.00-10.00' also matches
        normalised = text.replace(".", ":") if ":" not in text else text
        match = TIME.search(normalised) or TIME.search(text)
        if match:
            # match.group(1) and match.group(2) are full 'H:MM' strings
            return clock(match.group(1)), clock(match.group(2)), idx
    # Fallback: join all scanned cells and try once more
    blob = " ".join(blob_parts)
    match = TIME.search(blob.replace(".", ":")) or TIME.search(blob)
    if match:
        return clock(match.group(1)), clock(match.group(2)), 0
    return None

def is_lecture_enrolled_for_student(lecture_line: str, active_subscriptions: list) -> bool:
    """
    Checks if a lecture line from the timetable matches any of the student's active subscriptions,
    handling both batched courses (e.g., 'Product and Brand Management - Batch 1') 
    and non-batched courses (e.g., 'Fixed Income Securities').
    """
    lecture_line_lower = lecture_line.lower()

    for sub in active_subscriptions:
        sub_str = str(sub).strip()
        
        # Case A: Non-batched subject (e.g., "Fixed Income Securities" or "Systems Thinking")
        if "(" not in sub_str or "of" not in sub_str:
            base_sub_name = sub_str.lower()
            if base_sub_name in lecture_line_lower:
                return True
                
        # Case B: Batched subject (e.g., "Personal Selling and Sales Management (B1 of 3)")
        else:
            try:
                parts = sub_str.split('(')
                base_name = parts[0].strip().lower()
                batch_part = parts[1].split('of')[0].replace('b', '').strip()
                
                if base_name in lecture_line_lower:
                    if f"batch {batch_part}" in lecture_line_lower or f"(b{batch_part})" in lecture_line_lower:
                        return True
            except Exception:
                if sub_str.lower() in lecture_line_lower:
                    return True
                    
    return False

def _parse_timetable_sheet(ws):
    classes = []
    for row in ws.iter_rows(values_only=True):
        parsed = _row_time_range(row)
        if parsed is None:
            continue
        start_time, end_time, time_col = parsed
        for day, cell in zip(DAYS, row[time_col+1:time_col+7]):
            lines = [x.strip() for x in str(cell or '').splitlines() if x.strip()]
            for i, line in enumerate(lines):
                entry = ENTRY.match(line)
                
                # Fallback for non-batched courses (like Fixed Income Securities)
                if not entry:
                    if not line or line.startswith(('1)', '2)', '3)', '4)', '5)', '6)', '7)')):
                        continue
                    subject_name = line
                    batch_name = None
                    faculty = lines[i+1] if i+1 < len(lines) else None
                else:
                    course = entry.group(1)
                    batch = BATCH.search(course)
                    faculty = lines[i+1] if i+1 < len(lines) and not ENTRY.match(lines[i+1]) else None
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

def parse_timetable(path):
    wb = load_workbook(path, data_only=True, read_only=True)
    classes = []
    for ws in wb.worksheets:
        title = (ws.title or "").lower()
        if any(hint in title for hint in ("student", "testng", "allocation", "learners")):
            continue
        classes.extend(_parse_timetable_sheet(ws))
    if not classes and wb.active is not None:
        classes = _parse_timetable_sheet(wb.active)
    return classes


STUDENT_SHEET_HINTS = ("student", "roster", "testng", "learners", "enrol")
NAME_HEADERS = {"name", "student name", "full name", "student", "learner"}
EMAIL_HEADERS = {"email", "e-mail", "mail", "mailid", "mail id", "student email"}
BATCH_HEADERS = {"batch", "batch name", "batch id", "class", "section", "division", "group"}
PHONE_HEADERS = {"phone", "mobile", "contact", "phone number"}
ROLL_HEADERS = {
    "roll", "roll no", "roll number", "id", "student id", "enrolment", "enrollment",
    "prn", "prn no", "registration", "reg no", "regno", "imdr id", "imdr roll",
    "sap id", "permanent registration number",
}
ELECTIVE_HEADER_BATCH = re.compile(
    r"^(.*?)\s*[\(\[]\s*((?:batch\s*)?b?\s*\d+(?:\s*of\s*\d+)?)\s*[\)\]]\s*$",
    re.IGNORECASE,
)
ROLL_TOKEN = re.compile(r"(imdr[\s._-]*\d{4,}[\s._-]*\d+)", re.IGNORECASE)
SUBJECT_HEADERS = {
    "subject", "subjects", "course", "courses", "paper", "papers",
    "enrolled subject", "enrolled subjects", "enrolled course", "specialization",
}
SKIP_SUBJECT_HEADERS = {
    "sr", "sr no", "s no", "serial", "gender", "sex", "dob", "date of birth",
    "address", "city", "state", "program", "programme", "degree", "year",
    "semester", "status", "remarks", "comment", "father", "mother", "guardian",
    "attendance", "percentage", "percent", "marks", "score", "grade",
}


def _header_key(value) -> str:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(value or "").strip())
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _truthy_enrollment(value) -> bool:
    text = str(value or "").strip().lower()
    if not text or text in {"-", "na", "n/a", "no", "n", "0", "false", "none"}:
        return False
    return True


def _split_subjects(raw: str) -> list[str]:
    parts = re.split(r"[,;/|]|\n", str(raw or ""))
    return [part.strip() for part in parts if part.strip() and part.strip().lower() not in {"yes", "y", "no"}]


def _looks_like_batch(value: str) -> bool:
    return bool(re.search(r"batch|\bB\s*\d+\b|CS-\d|\bB\d+\s*of\s*\d+", str(value or ""), re.IGNORECASE))


def parse_elective_header(title: str) -> tuple[str, str]:
    text = str(title or "").strip()
    match = ELECTIVE_HEADER_BATCH.match(text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    match = re.match(
        r"^(.*?)\s*[-–]\s*((?:batch\s*)?b?\s*\d+(?:\s*of\s*\d+)?)\s*$",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return text, ""


def _extract_roll(cells, header_map) -> str:
    for value in cells:
        text = str(value or "").strip()
        match = ROLL_TOKEN.search(text)
        if match:
            return re.sub(r"\s+", "", match.group(1)).strip()
    idx = header_map.get("roll_no")
    if idx is not None and idx < len(cells) and cells[idx] is not None:
        value = str(cells[idx]).strip()
        if value and not value.isdigit():
            return value
    return ""


def _row_enrollments(header_map: dict, cells: list, default_batch: str) -> list[dict]:
    enrollments = []

    def add_enroll(subject, enroll_batch=None):
        header_subject, header_batch = parse_elective_header(subject)
        subject_name = header_subject or str(subject or "").strip()
        if not subject_name:
            return
        enrollments.append({
            "subject": subject_name,
            "batch": str(enroll_batch or header_batch or default_batch or "").strip(),
        })

    subject_cell = ""
    idx = header_map.get("subject")
    if idx is not None and idx < len(cells) and cells[idx] is not None:
        subject_cell = str(cells[idx]).strip()
    for subject_name in _split_subjects(subject_cell):
        add_enroll(subject_name, default_batch)
    used = header_map.get("identity_idxs") or set()
    col_titles = header_map.get("col_titles") or {}
    for col_idx in header_map.get("subject_cols") or []:
        if col_idx in used or col_idx >= len(cells):
            continue
        value = cells[col_idx]
        if not _truthy_enrollment(value):
            continue
        header_title = col_titles.get(col_idx) or ""
        cell_text = str(value).strip()
        _, header_batch = parse_elective_header(header_title)
        cell_subject, cell_batch = parse_elective_header(cell_text)
        if cell_batch and cell_subject and cell_subject.lower() not in {"yes", "y", "true", "enrolled"}:
            add_enroll(cell_subject, cell_batch)
        elif _looks_like_batch(cell_text) and cell_text.lower() not in {"yes", "y", "1", "true", "enrolled"}:
            add_enroll(header_title, cell_text)
        elif header_batch:
            add_enroll(header_title, header_batch)
        elif default_batch and cell_text.lower() in {"yes", "y", "1", "true", "enrolled"}:
            add_enroll(header_title or cell_text, default_batch)
    return enrollments


def _map_student_headers(cells) -> dict:
    mapping = {}
    subject_cols = []
    col_titles = {}
    identity_idxs = set()
    for idx, cell in enumerate(cells):
        key = _header_key(cell)
        title = str(cell or "").strip()
        if not key:
            continue
        col_titles[idx] = title
        _, header_batch = parse_elective_header(title)
        if header_batch:
            subject_cols.append(idx)
            continue
        if key in NAME_HEADERS or (key.endswith(" name") and "father" not in key and "mother" not in key):
            mapping.setdefault("name", idx)
            identity_idxs.add(idx)
        elif key in EMAIL_HEADERS:
            mapping.setdefault("email", idx)
            identity_idxs.add(idx)
        elif key in BATCH_HEADERS or key == "batch":
            mapping.setdefault("batch", idx)
            identity_idxs.add(idx)
        elif key in PHONE_HEADERS:
            mapping.setdefault("phone", idx)
            identity_idxs.add(idx)
        elif key in ROLL_HEADERS or "roll" in key.split() or key in {"prn", "prn no"} or key.endswith(" prn"):
            mapping.setdefault("roll_no", idx)
            identity_idxs.add(idx)
        elif key in SUBJECT_HEADERS or "subject" in key or "course" in key:
            mapping.setdefault("subject", idx)
            identity_idxs.add(idx)
        elif key not in SKIP_SUBJECT_HEADERS:
            subject_cols.append(idx)
    mapping["subject_cols"] = subject_cols
    mapping["col_titles"] = col_titles
    mapping["identity_idxs"] = identity_idxs
    return mapping if "name" in mapping or "email" in mapping or "roll_no" in mapping else {}


def parse_student_roster(path) -> list[dict]:
    """Read student enrollments from sheets such as Students-Testng."""
    wb = load_workbook(path, data_only=True, read_only=True)
    by_identity: dict[str, dict] = {}
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
            roll_no = _extract_roll(cells, header_map)
            if not name and not email and not roll_no:
                continue
            identity = email or (roll_no.lower() if roll_no else "") or name.lower()
            person = by_identity.setdefault(identity, {
                "name": name,
                "email": email,
                "batch": batch,
                "phone": cell("phone"),
                "roll_no": roll_no,
                "sheet": ws.title,
                "enrollments": [],
            })
            if name and not person.get("name"):
                person["name"] = name
            if email and not person.get("email"):
                person["email"] = email
            if batch and not person.get("batch"):
                person["batch"] = batch
            if not person.get("roll_no"):
                person["roll_no"] = _extract_roll(cells, header_map)
            person["enrollments"].extend(_row_enrollments(header_map, cells, batch or person.get("batch") or ""))

        if preferred and ws in preferred and by_identity:
            break
    return list(by_identity.values())


ALLOCATION_SHEET_HINTS = ("allocation", "elective", "batch alloc", "subject batch")


def parse_batch_allocation(path) -> list[dict]:
    """Read elective/subject batch rows from a Batch Allocation sheet."""
    wb = load_workbook(path, data_only=True, read_only=True)
    people = []
    for ws in wb.worksheets:
        title = (ws.title or "").lower()
        if not any(hint in title for hint in ALLOCATION_SHEET_HINTS):
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
            subject = cell("subject")
            roll_no = _extract_roll(cells, header_map)
            if not name and not email and not roll_no:
                continue
            enrollments = _row_enrollments(header_map, cells, batch)
            if not enrollments and (subject or batch):
                enrollments.append({"subject": subject, "batch": batch})
            people.append({
                "name": name,
                "email": email,
                "batch": batch,
                "phone": "",
                "roll_no": roll_no,
                "sheet": ws.title,
                "enrollments": enrollments,
                "subject": subject,
            })
    return people