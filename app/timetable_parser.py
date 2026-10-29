import re
from dataclasses import dataclass

from openpyxl import load_workbook

TIME=re.compile(r"^\s*(\d{1,2}(?::\d{2})?)\s*(?:-|–|to)\s*(\d{1,2}(?::\d{2})?)\s*$",re.IGNORECASE)
ENTRY=re.compile(r"^\s*\d+\)\s*(.+?)\s*$")
BATCH=re.compile(r"(?:-|–)?\s*(?:Batch|B)\s*(\d+)(?:\s*of\s*\d+)?\s*$",re.IGNORECASE)
DAYS=["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]
@dataclass
class ParsedClass: weekday:str; start_time:str; end_time:str; subject:str; batch:str|None; faculty_name:str|None
def clock(value): value=value.strip(); return value if ":" in value else f"{value}:00"

def _parse_timetable_sheet(ws):
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
EMAIL_HEADERS = {"email", "e-mail", "mail", "student email"}
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
}


def _header_key(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()


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
        if _looks_like_batch(cell_text) and cell_text.lower() not in {"yes", "y", "1", "true", "enrolled"}:
            add_enroll(header_title, cell_text)
        else:
            add_enroll(header_title or cell_text, header_batch or default_batch)
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
        elif key in ROLL_HEADERS:
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
    return mapping if "name" in mapping or "email" in mapping else {}


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
            if not name and not email:
                continue
            identity = email or name.lower()
            person = by_identity.setdefault(identity, {
                "name": name,
                "email": email,
                "batch": batch,
                "phone": cell("phone"),
                "roll_no": _extract_roll(cells, header_map),
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
            if not name and not email:
                continue
            enrollments = _row_enrollments(header_map, cells, batch)
            if not enrollments and (subject or batch):
                enrollments.append({"subject": subject, "batch": batch})
            people.append({
                "name": name,
                "email": email,
                "batch": batch,
                "phone": "",
                "roll_no": _extract_roll(cells, header_map),
                "sheet": ws.title,
                "enrollments": enrollments,
                "subject": subject,
            })
    return people
