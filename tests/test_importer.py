"""Reading the clinic's own spreadsheet without quietly ruining their CRM.

Until the clinic's Excel file is in, the recovery engine can only see patients
who arrive after installation day — and every opportunity worth recovering is
by definition already in the past. So the import is what decides whether a pilot
has anything to find.

It is also the only operation in this product that can write several thousand
wrong rows in one second with no undo. Everything here is about the ways a real
Vietnamese customer file breaks a naive parser:

  * Excel stores 0912345678 as the number 912345678 and loses the leading zero.
    Phone is the identity everything else matches on, so a column of those
    imports as a column of strangers.
  * "1.500.000" is one and a half million here and 1.5 almost everywhere else.
  * "15/03/2025" is March, not day 15 of month 3.
  * A "không liên hệ" column in the clinic's own file is a refusal that has to
    survive the import — messaging those people would be the worst possible
    first act of a new system.
"""
import datetime
import io

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models.models import (
    Appointment, Branch, Clinic, Doctor, PatientLead, RevenueRecord, Service,
)
from backend.app.services import importer

engine = create_engine("sqlite:///:memory:")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=engine)
    s = TestingSessionLocal()
    yield s
    s.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def clinic(db):
    c = Clinic(name="CareDesk", is_active=True)
    db.add(c)
    db.flush()
    db.add_all([
        Branch(clinic_id=c.id, name="CS1", address="1 Lê Lợi", is_active=True),
        Doctor(clinic_id=c.id, name="BS An", is_active=True),
        Service(clinic_id=c.id, name="Điều trị mụn", price=500_000, duration_minutes=45,
                revisit_interval_days=30),
        Service(clinic_id=c.id, name="Laser CO2", price=2_000_000, duration_minutes=60),
    ])
    db.commit()
    return c


def _xlsx(rows):
    """A real .xlsx in memory, so the test exercises the same path a clinic does."""
    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


#: A file shaped like the ones clinics actually keep: Vietnamese headers, a
#: phone column Excel has turned into numbers, money with dots, day-first dates.
REAL_FILE = [
    ["Họ tên", "SĐT", "Dịch vụ", "Ngày khám", "Trạng thái", "Doanh thu", "Ghi chú"],
    ["Nguyễn Thị Hoa", 912345678, "Điều trị mụn", "15/03/2025", "Đã đến", "1.500.000", "Da nhạy cảm"],
    ["Trần Văn Bình", "0987654321", "Laser CO2", "20/03/2025", "Đã đến", "2.000.000", ""],
    ["Lê Thị Cúc", "0911222333", "Điều trị mụn", "01/04/2025", "Hủy", "", "Đổi lịch"],
]


# --- the column mapping is proposed, never applied ---------------------------

def test_the_mapping_is_proposed_with_five_real_rows_to_check_it_against(clinic):
    """A mapping is far easier to verify against the clinic's own data than
    against a list of field names."""
    result = importer.preview(_xlsx(REAL_FILE), "khach.xlsx")

    assert result["row_count"] == 3
    assert len(result["sample_rows"]) == 3
    assert result["suggested_mapping"]["full_name"] == 0
    assert result["suggested_mapping"]["phone"] == 1
    assert result["suggested_mapping"]["revenue"] == 5
    assert result["ready"] is True


def test_a_file_missing_a_phone_column_is_refused_by_name(clinic):
    """Not "invalid file". The receptionist has to know which column to add."""
    result = importer.preview(_xlsx([["Họ tên", "Ghi chú"], ["A", "x"]]), "a.xlsx")

    assert result["ready"] is False
    assert "Số điện thoại" in result["missing_required"]


def test_an_exact_header_beats_a_substring_one(clinic):
    """A file with both "Tên" and "Tên dịch vụ" must not hand the service column
    to the patient's name."""
    rows = [["Tên dịch vụ", "Tên", "SĐT"], ["Điều trị mụn", "Chị Hoa", "0911222333"]]

    mapping = importer.preview(_xlsx(rows), "a.xlsx")["suggested_mapping"]

    assert mapping["full_name"] == 1
    assert mapping["service"] == 0


def test_nothing_is_written_by_a_preview(db, clinic):
    importer.preview(_xlsx(REAL_FILE), "khach.xlsx")

    assert db.query(PatientLead).count() == 0


# --- what Excel does to a phone number ---------------------------------------

@pytest.mark.parametrize("stored, expected", [
    (912345678, "0912345678"),      # the column was typed as Number
    (912345678.0, "0912345678"),    # ... and came back as a float
    ("0912345678", "0912345678"),
    ("+84912345678", "0912345678"),
    ("84912345678", "0912345678"),
    ("0912 345 678", "0912345678"),
    ("0912.345.678", "0912345678"),
    ("", None),
    ("không có", None),
    ("123", None),                  # too short to be a phone at all
])
def test_the_leading_zero_excel_threw_away_is_put_back(stored, expected):
    assert importer.normalize_phone(stored) == expected


def test_a_row_without_a_usable_phone_is_skipped_and_named(db, clinic):
    """Skipped, not invented. And the row number is reported, because "3 rows
    failed" with no line numbers is not something anyone can fix."""
    rows = [["Họ tên", "SĐT"], ["Chị Hoa", "0911222333"], ["Khách lạ", "chưa có"]]

    result = importer.run_import(db, clinic.id, _xlsx(rows), "a.xlsx",
                                 {"full_name": 0, "phone": 1}, dry_run=True)

    assert result["skipped"] == 1
    assert result["problems"][0]["row"] == 3


# --- money and dates ----------------------------------------------------------

@pytest.mark.parametrize("stored, expected", [
    ("1.500.000", 1_500_000),    # Vietnamese
    ("1,500,000", 1_500_000),    # exported from software that thinks in English
    ("1.500.000 đ", 1_500_000),
    (1_500_000, 1_500_000),
    ("2,5", 2.5),
    ("", None),
])
def test_money_is_read_in_both_conventions(stored, expected):
    """A dropped revenue figure is an opportunity that looks worthless."""
    assert importer.parse_amount(stored) == expected


@pytest.mark.parametrize("stored, expected", [
    ("15/03/2025", datetime.date(2025, 3, 15)),
    ("15-03-2025", datetime.date(2025, 3, 15)),
    ("2025-03-15", datetime.date(2025, 3, 15)),
    ("03/15/2025", None),        # month-first is refused, not reinterpreted
    ("chưa rõ", None),
])
def test_dates_are_read_day_first(stored, expected):
    """Guessing month-first would put a revisit reminder months out of place."""
    assert importer.parse_date(stored) == expected


# --- the history is the point -------------------------------------------------

def test_a_completed_visit_becomes_an_appointment_and_its_revenue(db, clinic):
    """This is what makes the import worth doing: overdue_revisit can only find
    somebody if there is a past visit with a date."""
    mapping = {"full_name": 0, "phone": 1, "service": 2, "visit_date": 3,
               "status": 4, "revenue": 5, "note": 6}

    result = importer.run_import(db, clinic.id, _xlsx(REAL_FILE), "khach.xlsx",
                                 mapping, dry_run=False)

    assert result["patients_created"] == 3
    assert result["visits_created"] == 2, "dòng 'Hủy' không được tính là đã khám"
    assert result["revenue_recorded"] == 3_500_000
    assert db.query(Appointment).filter(Appointment.status == "completed").count() == 2
    assert db.query(RevenueRecord).count() == 2


def test_an_imported_history_is_what_lets_the_engine_find_anyone(db, clinic):
    """The whole chain, end to end: a spreadsheet row from months ago becomes a
    patient who is overdue for a revisit today."""
    from backend.app.services import revenue_recovery as rr

    long_ago = (datetime.date.today() - datetime.timedelta(days=90)).strftime("%d/%m/%Y")
    rows = [["Họ tên", "SĐT", "Dịch vụ", "Ngày khám", "Doanh thu"],
            ["Chị Hoa", "0911222333", "Điều trị mụn", long_ago, "500.000"]]

    importer.run_import(db, clinic.id, _xlsx(rows), "a.xlsx",
                        {"full_name": 0, "phone": 1, "service": 2, "visit_date": 3,
                         "revenue": 4}, dry_run=False)
    rr.run_detection(db, clinic.id)

    found = db.query(rr.RevenueOpportunity).filter(
        rr.RevenueOpportunity.opportunity_type == rr.OVERDUE_REVISIT).all()
    assert len(found) == 1, "nhập lịch sử xong mà engine vẫn không tìm ra ai"


def test_a_service_that_matches_nothing_imports_the_patient_but_not_the_visit(db, clinic):
    """No visit is cheaper to fix than a visit filed under the wrong service,
    which starts the wrong revisit clock and books the wrong price as revenue —
    and nobody notices for months."""
    rows = [["Họ tên", "SĐT", "Dịch vụ", "Ngày khám"],
            ["Chị Hoa", "0911222333", "Dịch vụ lạ hoắc", "15/03/2025"]]

    result = importer.run_import(db, clinic.id, _xlsx(rows), "a.xlsx",
                                 {"full_name": 0, "phone": 1, "service": 2,
                                  "visit_date": 3}, dry_run=False)

    assert result["patients_created"] == 1
    assert result["visits_created"] == 0
    assert any("Dịch vụ" in p["reason"] for p in result["problems"])


def test_a_row_with_no_date_never_invents_a_visit(db, clinic):
    """An invented visit date invents a revisit schedule, and the patient is
    messaged about a treatment they may never have had."""
    rows = [["Họ tên", "SĐT", "Dịch vụ", "Ngày khám"],
            ["Chị Hoa", "0911222333", "Điều trị mụn", ""]]

    result = importer.run_import(db, clinic.id, _xlsx(rows), "a.xlsx",
                                 {"full_name": 0, "phone": 1, "service": 2,
                                  "visit_date": 3}, dry_run=False)

    assert result["patients_created"] == 1
    assert result["visits_created"] == 0


# --- not writing things twice -------------------------------------------------

def test_importing_the_same_file_twice_does_not_duplicate_anybody(db, clinic):
    """Clinics re-upload. They add a few rows and send the whole file again, and
    a naive importer turns one patient into three — the exact duplication this
    system already fought once at the booking form."""
    mapping = {"full_name": 0, "phone": 1, "service": 2, "visit_date": 3,
               "status": 4, "revenue": 5, "note": 6}
    importer.run_import(db, clinic.id, _xlsx(REAL_FILE), "a.xlsx", mapping, dry_run=False)
    second = importer.run_import(db, clinic.id, _xlsx(REAL_FILE), "a.xlsx", mapping,
                                 dry_run=False)

    assert second["patients_created"] == 0
    assert second["patients_updated"] == 3
    assert db.query(PatientLead).count() == 3
    assert db.query(Appointment).count() == 2, "lượt khám cũ bị nhập lại lần hai"
    assert db.query(RevenueRecord).count() == 2, "doanh thu bị đếm hai lần"


def test_a_dry_run_reports_everything_and_writes_nothing(db, clinic):
    """The default, and the UI runs one every time. There is no undo for this."""
    mapping = {"full_name": 0, "phone": 1, "service": 2, "visit_date": 3,
               "status": 4, "revenue": 5, "note": 6}

    result = importer.run_import(db, clinic.id, _xlsx(REAL_FILE), "khach.xlsx",
                                 mapping, dry_run=True)

    assert result["dry_run"] is True
    assert result["patients_created"] == 3, "phải báo cáo đúng như khi chạy thật"
    assert db.query(PatientLead).count() == 0
    assert db.query(Appointment).count() == 0


# --- the refusal in their own file --------------------------------------------

def test_a_do_not_contact_column_survives_the_import(db, clinic):
    """Importing a refusal and then messaging the person anyway would be the
    worst possible first act of a new system."""
    rows = [["Họ tên", "SĐT", "Không liên hệ"],
            ["Chị Hoa", "0911222333", "x"],
            ["Anh Bình", "0987654321", ""]]

    result = importer.run_import(db, clinic.id, _xlsx(rows), "a.xlsx",
                                 {"full_name": 0, "phone": 1, "opt_out": 2},
                                 dry_run=False)

    assert result["opted_out"] == 1
    refused = db.query(PatientLead).filter(PatientLead.phone == "0911222333").one()
    assert refused.contact_opt_out is True
    assert refused.opt_out_reason == "imported"


def test_an_imported_refusal_keeps_the_patient_out_of_the_money_queue(db, clinic):
    """The flag is only worth having if it reaches the screen where staff pick
    up the phone."""
    from backend.app.services import revenue_recovery as rr

    long_ago = (datetime.date.today() - datetime.timedelta(days=90)).strftime("%d/%m/%Y")
    rows = [["Họ tên", "SĐT", "Dịch vụ", "Ngày khám", "Không liên hệ"],
            ["Chị Hoa", "0911222333", "Điều trị mụn", long_ago, "x"]]
    importer.run_import(db, clinic.id, _xlsx(rows), "a.xlsx",
                        {"full_name": 0, "phone": 1, "service": 2, "visit_date": 3,
                         "opt_out": 4}, dry_run=False)

    rr.run_detection(db, clinic.id)

    assert db.query(rr.RevenueOpportunity).count() >= 1, "vẫn phát hiện được cơ hội"
    assert rr.money_queue(db, clinic.id) == [], "khách đã từ chối vẫn nằm trong hàng đợi gọi"


# --- files that are not what they claim ---------------------------------------

def test_an_old_xls_is_refused_with_the_way_out(clinic):
    """"Unsupported format" leaves the clinic stuck. Telling them to Save As
    .xlsx takes ten seconds."""
    with pytest.raises(ValueError, match="Save As"):
        importer.read_table(b"\xd0\xcf\x11\xe0", "khach.xls")


def test_a_csv_with_semicolons_still_reads(clinic):
    """Excel on a Vietnamese Windows saves CSV with semicolons, and half the
    files a clinic sends look like this."""
    content = "Họ tên;SĐT\nChị Hoa;0911222333\n".encode("utf-8")

    headers, rows = importer.read_table(content, "khach.csv")

    assert headers == ["Họ tên", "SĐT"]
    assert rows[0][1] == "0911222333"


def test_a_file_with_no_header_row_is_refused(clinic):
    with pytest.raises(ValueError):
        importer.read_table(b"", "khach.csv")
