"""Booking without chat, and moving an appointment instead of losing it.

Both exist for the same reason: a booking the clinic would otherwise never get.
A real share of patients open the chat, see a conversation starting, and close
the tab — and a patient who cannot make Thursday cancels rather than rebooking.
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
    Appointment, BookingRequest, Branch, Clinic, Doctor, DoctorTimeOff,
    PatientLead, ReminderLog, Service, WorkingSchedule,
)
from backend.app.services.reminder import make_public_token

# StaticPool: an in-memory SQLite database lives inside its connection, so the
# default pool hands the next checkout a brand-new empty database. Endpoints
# that commit mid-request would then find no tables at all.
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
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def clinic(db):
    """One clinic, one branch, one doctor working every day, one service."""
    from backend.app.core.slug import assign_slug

    c = Clinic(name="Phòng khám CareDesk", is_active=True, landing_enabled=True)
    db.add(c)
    db.flush()
    assign_slug(db, c)
    branch = Branch(clinic_id=c.id, name="Quan 1", address="1 Le Loi",
                    is_active=True, landing_enabled=True)
    db.add(branch)
    db.flush()
    assign_slug(db, branch)
    service = Service(clinic_id=c.id, name="Tri mun", price=500000, duration_minutes=30)
    doctor = Doctor(clinic_id=c.id, name="BS An", branch_id=branch.id, is_active=True)
    db.add_all([service, doctor])
    db.flush()
    for day in range(7):
        db.add(WorkingSchedule(doctor_id=doctor.id, branch_id=branch.id, day_of_week=day,
                               start_time=datetime.time(8, 0), end_time=datetime.time(17, 0)))
    db.commit()
    return {"clinic": c, "branch": branch, "service": service, "doctor": doctor}


def _tomorrow():
    return (datetime.date.today() + datetime.timedelta(days=1)).isoformat()


# --- the form is reachable and self-contained --------------------------------

def test_the_landing_page_offers_booking_without_chat(client, clinic):
    """The whole point: a patient who will not chat still has a way through."""
    page = client.get(f"/book/{clinic['clinic'].slug}").text
    assert f"/book/{clinic['clinic'].slug}/dat-lich" in page


def test_the_form_renders_and_lists_services(client, clinic):
    page = client.get(f"/book/{clinic['clinic'].slug}/dat-lich")
    assert page.status_code == 200
    assert "Tri mun" in page.text


def test_the_form_shows_real_slots_for_a_chosen_day(client, clinic):
    page = client.get(f"/book/{clinic['clinic'].slug}/dat-lich", params={
        "service": clinic["service"].id, "day": _tomorrow(),
    })
    assert page.status_code == 200
    assert "08:00" in page.text


def test_a_day_the_doctor_is_off_offers_nothing(client, clinic, db):
    """Same leave rules as the AI path — one calendar, not two."""
    db.add(DoctorTimeOff(clinic_id=clinic["clinic"].id, doctor_id=clinic["doctor"].id,
                         start_date=datetime.date.fromisoformat(_tomorrow()),
                         end_date=datetime.date.fromisoformat(_tomorrow())))
    db.commit()

    page = client.get(f"/book/{clinic['clinic'].slug}/dat-lich", params={
        "service": clinic["service"].id, "day": _tomorrow(),
    })
    assert "08:00" not in page.text
    assert "kín lịch" in page.text or "nghỉ" in page.text


def test_the_form_is_never_cached(client, clinic):
    """A half-filled form served from a cache would show one patient another's
    partially entered booking."""
    page = client.get(f"/book/{clinic['clinic'].slug}/dat-lich")
    assert "no-store" in page.headers.get("cache-control", "")


# --- submitting ---------------------------------------------------------------

def _submit(client, clinic, **overrides):
    data = {
        "branch_slug": clinic["branch"].slug,
        "service_id": str(clinic["service"].id),
        "day": _tomorrow(),
        "slot": "09:00",
        "full_name": "Nguyen Van A",
        "phone": "0901234567",
        "consent": "1",
        "locale": "vi",
    }
    data.update(overrides)
    return client.post(f"/book/{clinic['clinic'].slug}/dat-lich", data=data,
                       follow_redirects=False)


def test_a_valid_submission_creates_a_request_not_an_appointment(client, clinic, db):
    """Same rule the public chat follows: an unauthenticated visitor can ask for
    a slot, not take one. Otherwise a bot filling in the form occupies the
    doctor's real calendar."""
    res = _submit(client, clinic)

    assert res.status_code == 303
    assert "done=1" in res.headers["location"]
    assert db.query(BookingRequest).count() == 1
    assert db.query(Appointment).count() == 0

    req = db.query(BookingRequest).first()
    assert req.full_name == "Nguyen Van A"
    assert req.contact_value == "0901234567"
    assert "09:00" in req.preferred_time

    patient = db.query(PatientLead).first()
    assert patient.consent_given is True
    assert patient.consent_timestamp is not None
    assert patient.source == "web_form"


def test_a_bad_phone_number_is_rejected(client, clinic, db):
    res = _submit(client, clinic, phone="12345")
    assert res.status_code == 303
    assert "err=" in res.headers["location"]
    assert db.query(BookingRequest).count() == 0


def test_a_missing_name_is_rejected(client, clinic, db):
    res = _submit(client, clinic, full_name=" ")
    assert "err=" in res.headers["location"]
    assert db.query(BookingRequest).count() == 0


def test_consent_is_required(client, clinic, db):
    """Storing a phone number to call back needs permission on the record."""
    res = _submit(client, clinic, consent="")
    assert "err=" in res.headers["location"]
    assert db.query(PatientLead).count() == 0


def test_a_slot_taken_since_the_page_loaded_is_refused(client, clinic, db):
    """The page may have been open for an hour. The slot is re-checked at submit
    rather than trusted from the form."""
    start = datetime.datetime.combine(
        datetime.date.fromisoformat(_tomorrow()), datetime.time(9, 0))
    p = PatientLead(clinic_id=clinic["clinic"].id, full_name="Khach khac", consent_given=True)
    db.add(p)
    db.flush()
    db.add(Appointment(
        clinic_id=clinic["clinic"].id, branch_id=clinic["branch"].id,
        service_id=clinic["service"].id, doctor_id=clinic["doctor"].id,
        patient_id=p.id, status="confirmed",
        start_time=start, end_time=start + datetime.timedelta(minutes=30)))
    db.commit()

    res = _submit(client, clinic, slot="09:00")
    assert "err=" in res.headers["location"]
    assert db.query(BookingRequest).count() == 0


def test_a_booking_request_event_is_emitted(client, clinic, db):
    """It cancels the pending price-follow-up: someone who just booked must not
    then be nudged about the price they already accepted."""
    from backend.app.models.models import DomainEvent

    _submit(client, clinic)
    events = [e.event_type for e in db.query(DomainEvent).all()]
    assert "booking_request_created" in events


# --- rescheduling -------------------------------------------------------------

@pytest.fixture
def appointment(db, clinic):
    start = datetime.datetime.combine(
        datetime.date.fromisoformat(_tomorrow()), datetime.time(14, 0))
    p = PatientLead(clinic_id=clinic["clinic"].id, full_name="Khach", phone="0900000001",
                    consent_given=True)
    db.add(p)
    db.flush()
    a = Appointment(clinic_id=clinic["clinic"].id, branch_id=clinic["branch"].id,
                    service_id=clinic["service"].id, doctor_id=clinic["doctor"].id,
                    patient_id=p.id, status="confirmed",
                    start_time=start, end_time=start + datetime.timedelta(minutes=30))
    db.add(a)
    db.commit()
    return a


def _resched(client, appt, **params):
    params.setdefault("token", make_public_token(appt.id))
    return client.get(f"/api/v1/public/appointments/{appt.id}/reschedule", params=params)


def test_reschedule_offers_days_that_actually_have_room(client, appointment):
    page = _resched(client, appointment)
    assert page.status_code == 200
    assert "Chọn giờ mới" in page.text
    assert "reschedule?token=" in page.text


def test_reschedule_moves_the_appointment(client, appointment, db):
    new_day = (datetime.date.today() + datetime.timedelta(days=2)).isoformat()
    page = _resched(client, appointment, day=new_day, slot="10:30")

    assert "Đã đổi lịch" in page.text
    db.refresh(appointment)
    assert appointment.start_time.strftime("%H:%M") == "10:30"
    assert appointment.start_time.date().isoformat() == new_day
    assert appointment.status == "confirmed", "đổi giờ không được huỷ lịch"


def test_rescheduling_clears_the_old_reminders(client, appointment, db):
    """The sent reminders describe a time that no longer exists, so they must be
    dropped for fresh ones to go out for the new slot."""
    db.add(ReminderLog(appointment_id=appointment.id, kind="24h", medium="phone",
                       channel="sms", status="sent", attempts=1))
    db.commit()
    assert db.query(ReminderLog).count() == 1

    new_day = (datetime.date.today() + datetime.timedelta(days=2)).isoformat()
    _resched(client, appointment, day=new_day, slot="11:00")
    assert db.query(ReminderLog).count() == 0


def test_a_taken_slot_cannot_be_rescheduled_into(client, appointment, db, clinic):
    new_day = datetime.date.today() + datetime.timedelta(days=2)
    start = datetime.datetime.combine(new_day, datetime.time(10, 30))
    p = PatientLead(clinic_id=clinic["clinic"].id, full_name="Khac", consent_given=True)
    db.add(p)
    db.flush()
    db.add(Appointment(clinic_id=clinic["clinic"].id, branch_id=clinic["branch"].id,
                       service_id=clinic["service"].id, doctor_id=clinic["doctor"].id,
                       patient_id=p.id, status="confirmed",
                       start_time=start, end_time=start + datetime.timedelta(minutes=30)))
    db.commit()

    page = _resched(client, appointment, day=new_day.isoformat(), slot="10:30")
    assert "đã có người đặt" in page.text
    db.refresh(appointment)
    assert appointment.start_time.strftime("%H:%M") == "14:00", "lịch cũ phải giữ nguyên"


def test_a_bad_token_cannot_reschedule(client, appointment):
    page = _resched(client, appointment, token="sai-token")
    assert page.status_code in (403, 404)


def test_a_cancelled_appointment_cannot_be_moved(client, appointment, db):
    appointment.status = "cancelled"
    db.commit()
    page = _resched(client, appointment)
    assert "Không đổi được" in page.text


def test_the_reminder_offers_all_three_actions(clinic, appointment):
    """Confirm and cancel alone push "I can't make it" straight to a lost
    booking."""
    from backend.app.services.reminder import build_reminder_text

    text = build_reminder_text(appointment, "24h")
    assert "/confirm?token=" in text
    assert "/reschedule?token=" in text
    assert "/cancel?token=" in text
