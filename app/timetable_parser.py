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
