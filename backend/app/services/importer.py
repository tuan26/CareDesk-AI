"""Read the clinic's own customer file, because that is where the money is.

A Vietnamese clinic keeps its patients in Excel. Until that file is in, the
recovery engine can only see people who arrive after installation day — and
every opportunity worth recovering is, by definition, already in the past. So
this is not a convenience feature; without it a pilot starts with an empty
detector and concludes the product finds nothing.

The hard part is not parsing. It is that no two of these files look alike:
columns in any order, in Vietnamese with or without diacritics, names like
"SĐT" or "Số điện thoại" or "Phone", dates written five ways. So nothing here
guesses silently. The file is read, the columns are *proposed* with a
confidence, and a human confirms the mapping before a single row is written.
The same principle as the revisit interval: suggest, never decide.

Three details that come from real spreadsheets rather than from imagination:

* Excel stores "0912345678" as the number 912345678 and drops the leading zero.
  Re-adding it is not optional — a phone is the identity this whole system
  matches patients on, so a column of numbers would import as a column of
  strangers.
* "1.500.000" is one and a half million in Vietnamese, and 1.5 in most parsers.
* "15/03/2025" is March. A parser that reads it as the 3rd of day 15 throws,
  and one that silently accepts month-first invents a revisit date months off.
"""
import csv
import datetime
import io
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.core import clock
from backend.app.models.models import (
    Appointment, Branch, Doctor, PatientLead, RevenueRecord, Service,
)
from backend.app.services.booking_flow import strip_accents
from backend.app.services.patients import upsert_lead

logger = logging.getLogger(__name__)

MAX_ROWS = 20_000
PREVIEW_ROWS = 5


# --- the fields we can actually use ------------------------------------------

#: Every field the importer understands, and the header words that point at it.
#: Matched on folded text, longest first, so "ngay hen" does not win over
#: "ngay hen tiep theo".
FIELDS: Dict[str, Dict[str, Any]] = {
    "full_name": {
        "label": "Họ tên",
        "required": True,
        "keywords": ("ho ten", "ten khach", "khach hang", "ten benh nhan",
                     "full name", "name", "ho va ten", "ten"),
    },
    "phone": {
        "label": "Số điện thoại",
        "required": True,
        "keywords": ("so dien thoai", "dien thoai", "sdt", "so dt", "phone",
                     "mobile", "lien he", "so may"),
    },
    "email": {
        "label": "Email",
        "keywords": ("email", "thu dien tu", "mail"),
    },
    "service": {
        "label": "Dịch vụ quan tâm",
        "keywords": ("dich vu", "nhu cau", "quan tam", "lieu trinh", "service",
                     "goi dich vu"),
    },
    "visit_date": {
        "label": "Ngày khám gần nhất",
        "keywords": ("ngay kham", "ngay den", "lan kham cuoi", "ngay thuc hien",
                     "ngay hen", "visit date", "ngay su dung", "ngay"),
    },
    "status": {
        "label": "Trạng thái đến khám",
        "keywords": ("trang thai", "tinh trang", "ket qua", "status",
                     "da den", "den kham"),
    },
    "revenue": {
        "label": "Doanh thu",
        "keywords": ("doanh thu", "so tien", "thanh tien", "tong tien", "gia tri",
                     "revenue", "amount", "da thanh toan", "chi phi"),
    },
    "source": {
        "label": "Nguồn khách",
        "keywords": ("nguon", "kenh", "source", "den tu"),
    },
    "note": {
        "label": "Ghi chú",
        "keywords": ("ghi chu", "note", "remark", "chu thich"),
    },
    "opt_out": {
        "label": "Không liên hệ",
        "keywords": ("khong lien he", "khong goi", "tu choi", "do not contact",
                     "dnc", "ngung lien he", "khong nhan tin"),
    },
}

REQUIRED_FIELDS = tuple(k for k, v in FIELDS.items() if v.get("required"))

#: Spreadsheet words that mean the visit happened. Anything else is treated as
#: not-yet-completed, which is the safe direction: inventing a completed visit
#: would invent revenue and start a revisit clock that should not be running.
_COMPLETED_WORDS = ("da den", "hoan thanh", "da kham", "xong", "completed",
                    "done", "da thuc hien", "thanh cong")
_TRUE_WORDS = ("x", "co", "yes", "true", "1", "da", "v", "y")


# --- parsing the things Excel mangles ----------------------------------------

def normalize_phone(value: Any) -> Optional[str]:
    """Put back the leading zero Excel threw away.

    A column typed as Number turns 0912345678 into 912345678. Phone is the
    identity every patient lookup in this system runs on, so a column of those
    imports as a column of strangers and every later match silently fails.
    """
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    digits = re.sub(r"[^\d+]", "", str(value).strip())
    if not digits:
        return None

    if digits.startswith("+84"):
        digits = "0" + digits[3:]
    elif digits.startswith("84") and len(digits) in (11, 12):
        digits = "0" + digits[2:]
    elif not digits.startswith("0") and len(digits) == 9:
        # The Excel-as-number case: nine digits missing their zero.
        digits = "0" + digits

    return digits if 9 <= len(digits) <= 11 else None


def parse_amount(value: Any) -> Optional[float]:
    """"1.500.000" is one and a half million here, not 1.5."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = re.sub(r"[^\d.,-]", "", str(value).strip())
    if not text:
        return None
    # Vietnamese convention: "." groups thousands, "," is the decimal point.
    # But files exported from other software arrive the English way round, and
    # "1,500,000" must not come back as None — a dropped revenue figure is an
    # opportunity that looks worthless.
    if "," in text and "." in text:
        # Whichever separator comes last is the decimal point.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif text.count(",") > 1 or re.search(r",\d{3}(\D|$)", text):
        text = text.replace(",", "")        # 1,500,000
    elif text.count(".") > 1 or re.search(r"\.\d{3}(\D|$)", text):
        text = text.replace(".", "")        # 1.500.000
    else:
        text = text.replace(",", ".")       # 2,5
    try:
        return float(text)
    except ValueError:
        return None


def parse_date(value: Any) -> Optional[datetime.date]:
    """Day first. "15/03/2025" is March, and reading it the American way would
    put a revisit reminder months out of place — or throw on 15 as a month and
    lose the row entirely."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value

    text = str(value).strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%y",
                "%d-%m-%y", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _is_truthy(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return strip_accents(str(value)).strip() in _TRUE_WORDS


def _is_completed(value: Any) -> bool:
    if value is None or value == "":
        return False
    folded = strip_accents(str(value)).strip()
    return any(word in folded for word in _COMPLETED_WORDS)


# --- reading the file --------------------------------------------------------

def read_table(content: bytes, filename: str) -> Tuple[List[str], List[List[Any]]]:
    """Headers and rows from .xlsx or .csv. Raises ValueError with a message a
    receptionist can act on rather than a stack trace."""
    name = (filename or "").lower()

    if name.endswith((".xlsx", ".xlsm")):
        import openpyxl

        try:
            book = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user as text
            raise ValueError(f"Không đọc được file Excel: {exc}") from exc
        sheet = book.active
        rows = [list(r) for r in sheet.iter_rows(max_row=MAX_ROWS + 1, values_only=True)]
        book.close()
    elif name.endswith(".csv"):
        for encoding in ("utf-8-sig", "utf-8", "cp1258", "latin-1"):
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("Không đọc được file CSV: bảng mã không nhận dạng được.")
        # Excel on a Vietnamese Windows saves CSV with semicolons.
        sample = text[:4096]
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
        rows = [r for r in csv.reader(io.StringIO(text), delimiter=delimiter)]
    elif name.endswith(".xls"):
        raise ValueError(
            "File .xls (Excel 2003) chưa hỗ trợ. Mở bằng Excel và chọn "
            "Save As → Excel Workbook (.xlsx) rồi tải lên lại."
        )
    else:
        raise ValueError("Chỉ nhận file .xlsx hoặc .csv.")

    rows = [r for r in rows if any(c not in (None, "") for c in r)]
    if not rows:
        raise ValueError("File không có dòng nào.")

    headers = ["" if h is None else str(h).strip() for h in rows[0]]
    if not any(headers):
        raise ValueError("Dòng đầu tiên phải là tiêu đề cột.")
    return headers, rows[1:]


def suggest_mapping(headers: List[str]) -> Dict[str, Dict[str, Any]]:
    """Propose which column is which, and say how sure it is.

    Never applied on its own. The clinic sees the proposal next to five real
    rows from their own file and confirms it — the same rule as the revisit
    interval, for the same reason: a wrong guess here quietly files half the
    patients under the wrong phone number.
    """
    folded = [strip_accents(h).strip() for h in headers]
    suggestion: Dict[str, Dict[str, Any]] = {}
    taken: set = set()

    # Exact header matches first, so a file with both "Tên" and "Tên dịch vụ"
    # does not hand the service column to full_name on a substring hit.
    for exact_pass in (True, False):
        for field, spec in FIELDS.items():
            if field in suggestion:
                continue
            for keyword in sorted(spec["keywords"], key=len, reverse=True):
                for index, header in enumerate(folded):
                    if index in taken or not header:
                        continue
                    hit = header == keyword if exact_pass else keyword in header
                    if hit:
                        suggestion[field] = {
                            "column": index,
                            "header": headers[index],
                            "confidence": "cao" if exact_pass else "vừa",
                        }
                        taken.add(index)
                        break
                if field in suggestion:
                    break
    return suggestion


def preview(content: bytes, filename: str) -> Dict[str, Any]:
    """What the file contains, what we think each column is, and what is missing."""
    headers, rows = read_table(content, filename)
    mapping = suggest_mapping(headers)
    missing = [FIELDS[f]["label"] for f in REQUIRED_FIELDS if f not in mapping]

    return {
        "filename": filename,
        "headers": headers,
        "row_count": len(rows),
        "sample_rows": [
            ["" if c is None else str(c) for c in row[:len(headers)]]
            for row in rows[:PREVIEW_ROWS]
        ],
        "suggested_mapping": {f: m["column"] for f, m in mapping.items()},
        "suggestion_detail": mapping,
        "fields": [
            {"key": k, "label": v["label"], "required": bool(v.get("required"))}
            for k, v in FIELDS.items()
        ],
        "missing_required": missing,
        "ready": not missing,
        "note": (
            "Kiểm tra lại cột trước khi nhập. Hệ thống chỉ gợi ý — gán sai cột "
            "số điện thoại sẽ tạo ra một loạt khách trùng lặp."
        ),
        "truncated": len(rows) >= MAX_ROWS,
    }


# --- writing it in ------------------------------------------------------------

def run_import(db: Session, clinic_id: int, content: bytes, filename: str,
               mapping: Dict[str, int], dry_run: bool = True) -> Dict[str, Any]:
    """Apply a confirmed mapping.

    Defaults to a dry run, and the UI runs one first every time. A spreadsheet
    import is the one operation here that can put thousands of wrong rows into a
    clinic's CRM in a second, and there is no undo button for it.

    Historical visits are what make this worth doing at all: a completed visit
    with a date is what lets overdue_revisit find anybody. A row without a
    recognisable date becomes a patient record only — never a visit invented to
    fill the gap.
    """
    headers, rows = read_table(content, filename)

    missing = [FIELDS[f]["label"] for f in REQUIRED_FIELDS if f not in mapping]
    if missing:
        raise ValueError(f"Thiếu cột bắt buộc: {', '.join(missing)}")

    services = {strip_accents(s.name): s
                for s in db.query(Service).filter(Service.clinic_id == clinic_id).all()}
    branch = db.query(Branch).filter(Branch.clinic_id == clinic_id).first()
    doctor = db.query(Doctor).filter(Doctor.clinic_id == clinic_id).first()

    def cell(row: List[Any], field: str) -> Any:
        index = mapping.get(field)
        if index is None or index >= len(row):
            return None
        return row[index]

    stats = {
        "rows_read": len(rows), "patients_created": 0, "patients_updated": 0,
        "visits_created": 0, "revenue_recorded": 0.0, "opted_out": 0, "skipped": 0,
    }
    problems: List[Dict[str, Any]] = []

    for line, row in enumerate(rows, start=2):
        name = cell(row, "full_name")
        phone = normalize_phone(cell(row, "phone"))
        name = str(name).strip() if name not in (None, "") else None

        if not phone:
            stats["skipped"] += 1
            if len(problems) < 50:
                problems.append({"row": line, "reason": "Số điện thoại trống hoặc không hợp lệ",
                                 "value": str(cell(row, "phone") or "")})
            continue
        if not name:
            stats["skipped"] += 1
            if len(problems) < 50:
                problems.append({"row": line, "reason": "Thiếu họ tên", "value": phone})
            continue

        existing = db.query(PatientLead).filter(
            PatientLead.clinic_id == clinic_id, PatientLead.phone == phone
        ).first()

        # One record per phone, same rule the chat and the booking form follow.
        lead = upsert_lead(db, clinic_id=clinic_id, phone=phone, full_name=name,
                           source="import")
        # Needed before the id is usable: a new lead is only queued at this
        # point, and an appointment built from lead.id would carry None.
        db.flush()
        if existing:
            stats["patients_updated"] += 1
        else:
            stats["patients_created"] += 1

        email = cell(row, "email")
        if email and not lead.email:
            lead.email = str(email).strip()
        note = cell(row, "note")
        if note:
            lead.note = str(note).strip()

        # A refusal recorded in the clinic's own file has to survive the import.
        # Importing it and then messaging the person anyway is the worst
        # possible first act of a new system.
        if _is_truthy(cell(row, "opt_out")):
            lead.contact_opt_out = True
            lead.opt_out_at = clock.now()
            lead.opt_out_reason = "imported"
            stats["opted_out"] += 1

        visit_date = parse_date(cell(row, "visit_date"))
        status_cell = cell(row, "status")
        # No status column at all: a dated row in a customer history is a visit
        # that happened. A status column that says otherwise is believed.
        completed = _is_completed(status_cell) if mapping.get("status") is not None else True

        if visit_date and completed and branch and doctor:
            service = _match_service(services, cell(row, "service"))
            if service:
                start = datetime.datetime.combine(visit_date, datetime.time(9, 0))
                already = db.query(Appointment).filter(
                    Appointment.clinic_id == clinic_id,
                    Appointment.patient_id == lead.id,
                    Appointment.service_id == service.id,
                    Appointment.start_time == start,
                ).first()
                if not already:
                    appointment = Appointment(
                        clinic_id=clinic_id, patient_id=lead.id, service_id=service.id,
                        doctor_id=doctor.id, branch_id=branch.id, status="completed",
                        start_time=start,
                        end_time=start + datetime.timedelta(minutes=service.duration_minutes or 30),
                        booking_source="import", completed_at=start,
                    )
                    db.add(appointment)
                    db.flush()
                    stats["visits_created"] += 1

                    amount = parse_amount(cell(row, "revenue"))
                    if amount and amount > 0:
                        db.add(RevenueRecord(
                            clinic_id=clinic_id, patient_id=lead.id,
                            appointment_id=appointment.id, amount=amount,
                            source="import", recorded_at=start,
                        ))
                        stats["revenue_recorded"] += amount
            elif len(problems) < 50 and cell(row, "service"):
                problems.append({
                    "row": line,
                    "reason": "Dịch vụ không khớp với dịch vụ nào trong hệ thống",
                    "value": str(cell(row, "service")),
                })

    if dry_run:
        db.rollback()
    else:
        db.commit()

    stats["dry_run"] = dry_run
    stats["problems"] = problems
    stats["problem_count"] = len(problems)
    return stats


def _match_service(services: Dict[str, Service], raw: Any) -> Optional[Service]:
    """Match the spreadsheet's wording to a service the clinic has configured.

    Returns None rather than the closest thing. A visit filed under the wrong
    service starts the wrong revisit clock and books the wrong price as revenue,
    and "no visit imported" is a much cheaper mistake to fix than "wrong visit
    imported" — which nobody will notice for months.
    """
    if not raw:
        return None
    folded = strip_accents(str(raw)).strip()
    if not folded:
        return None
    if folded in services:
        return services[folded]
    for name, service in services.items():
        if folded in name or name in folded:
            return service
    return None
