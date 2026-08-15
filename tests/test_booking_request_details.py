"""A request reception can act on without reopening the conversation.

The queue showed a request with no clinic and no doctor, from a conversation
that had discussed both. The chat pins a branch when the patient arrives and
names a doctor before it quotes times — then dropped them on the way to the
database.

The web form did keep the branch, by gluing its name onto the end of the
preferred time: "10:30 16/08/2026 — Chi nhánh Quận 10". Free text in a column
nobody can filter or assign by, and the chat wrote "2026-08-16 18:00" into the
same column, so one list showed two formats and reception read each row twice.
"""
import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.database import Base, get_db
from backend.app.main import app
from backend.app.models.models import (
    BookingRequest, Branch, Clinic, Conversation, Doctor, PatientLead, Service,
    User, WorkingSchedule,
)
from backend.app.services.booking_flow import handle_booking

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                       poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=engine)
    s = TestingSessionLocal()
    yield s
    s.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def setup(db):
    from backend.app.core.slug import assign_slug

    clinic = Clinic(name="CareDesk", is_active=True, landing_enabled=True)
    db.add(clinic)
    db.flush()
    assign_slug(db, clinic)
    branch = Branch(clinic_id=clinic.id, name="Chi nhánh Quận 10", address="123 Ba Tháng Hai",
                    is_active=True, landing_enabled=True)
    db.add(branch)
    db.flush()
    assign_slug(db, branch)
    service = Service(clinic_id=clinic.id, name="Khám da liễu", price=150000, duration_minutes=30)
    doctor = Doctor(clinic_id=clinic.id, name="Bác sĩ Nguyễn Văn A",
                    branch_id=branch.id, is_active=True)
    staff = User(email="le@caredesk.ai", password_hash="x", full_name="Lễ tân",
                 role="receptionist", clinic_id=clinic.id, is_active=True)
    patient = PatientLead(clinic_id=clinic.id, full_name="Phương Uyên", phone="0912345222")
    db.add_all([service, doctor, staff, patient])
    db.flush()
    for day in range(7):
        db.add(WorkingSchedule(doctor_id=doctor.id, branch_id=branch.id, day_of_week=day,
                               start_time=datetime.time(8, 0), end_time=datetime.time(20, 0)))
    conv = Conversation(clinic_id=clinic.id, patient_id=patient.id, branch_id=branch.id,
                        booking_state={"active": True, "service_id": service.id,
                                       "full_name": "Phương Uyên", "phone": "0912345222"})
    db.add(conv)
    db.commit()
    return {"clinic": clinic, "branch": branch, "service": service, "doctor": doctor,
            "staff": staff, "conv": conv}


@pytest.fixture
def client(db, setup):
    from backend.app.api.deps import verify_receptionist_or_above
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[verify_receptionist_or_above] = lambda: setup["staff"]
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _book_through_chat(db, setup):
    """Walk the chat flow to the point where a request is written."""
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    handle_booking(db, setup["conv"], tomorrow.strftime("ngày %d/%m/%Y"))
    handle_booking(db, setup["conv"], "1")
    return db.query(BookingRequest).first()


# --- what the chat records ----------------------------------------------------

def test_a_chat_request_names_the_location_and_the_doctor(db, setup):
    """Both were already in the conversation state when the request was written,
    and both were thrown away."""
    request = _book_through_chat(db, setup)

    assert request is not None
    assert request.branch_id == setup["branch"].id, "yêu cầu không ghi cơ sở"
    assert request.doctor_id == setup["doctor"].id, "yêu cầu không ghi bác sĩ"


def test_the_requested_time_is_a_timestamp_not_a_sentence(db, setup):
    request = _book_through_chat(db, setup)

    assert isinstance(request.preferred_at, datetime.datetime)
    assert request.preferred_at.date() == datetime.date.today() + datetime.timedelta(days=1)


def test_both_entry_points_read_the_same_way(db, setup, client):
    """The chat wrote "2026-08-16 18:00" and the form wrote "10:30 16/08/2026 —
    Chi nhánh Quận 10", in one column, in one list."""
    from backend.app.services.booking_flow import _fmt_slot

    chat = _book_through_chat(db, setup)
    when = datetime.datetime.combine(datetime.date(2026, 8, 16), datetime.time(10, 30))

    assert _fmt_slot(when, "vi") == "10:30 16/08/2026"
    # Same shape, whichever door the patient came through.
    assert chat.preferred_time == _fmt_slot(chat.preferred_at, "vi")


def test_the_branch_is_not_glued_onto_the_time_string(db, setup):
    """It is a column now — reception filters and assigns by location, which no
    amount of free text supports."""
    request = _book_through_chat(db, setup)

    assert setup["branch"].name not in (request.preferred_time or "")


# --- what reception sees ------------------------------------------------------

def test_the_queue_returns_names_not_ids(client, db, setup):
    """An id is not something anyone can act on."""
    _book_through_chat(db, setup)

    rows = client.get("/api/v1/booking-requests").json()

    assert rows, "hộp yêu cầu rỗng"
    assert rows[0]["branch_name"] == "Chi nhánh Quận 10"
    assert rows[0]["doctor_name"] == "Bác sĩ Nguyễn Văn A"
    assert rows[0]["preferred_at"] is not None


def test_an_older_request_without_a_branch_still_loads(client, db, setup):
    """Rows written before the columns existed keep their free text. A blank
    location is honest; guessing one from a string would not be."""
    db.add(BookingRequest(
        clinic_id=setup["clinic"].id, patient_id=None, service_id=setup["service"].id,
        service_or_need="Khám da liễu", preferred_time="10:30 16/08/2026 — Chi nhánh cũ",
        full_name="Khách cũ", contact_method="phone", contact_value="0900000000",
        locale="vi",
    ))
    db.commit()

    rows = client.get("/api/v1/booking-requests").json()
    old = [r for r in rows if r["full_name"] == "Khách cũ"]

    assert old and old[0]["branch_name"] is None
