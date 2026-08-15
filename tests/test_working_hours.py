"""Evening clinics, and the night shift that silently booked nobody.

Aesthetics clinics take a lot of their work after office hours — the patient
finishes at six and comes in at seven. Nothing in the product prevents that: a
doctor may hold several shifts on the same weekday, so 08:00–12:00 plus
18:00–22:00 opens the evening without touching the day.

What did not work was a shift written as 22:00–02:00. Slot generation walks
forwards from start to end, so a shift that ends before it starts produced
nothing at all — no error, no warning, an empty calendar and no reason for it.
Only the browser form guarded against it, which means any API client could
create one.
"""
import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.database import Base, get_db
from backend.app.main import app
from backend.app.models.models import Branch, Clinic, Doctor, User, WorkingSchedule
from backend.app.services.ai_engine import get_available_slots

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
    clinic = Clinic(name="CareDesk", is_active=True)
    db.add(clinic)
    db.flush()
    branch = Branch(clinic_id=clinic.id, name="CS1", address="1 Lê Lợi", is_active=True)
    db.add(branch)
    db.flush()
    doctor = Doctor(clinic_id=clinic.id, name="BS An", branch_id=branch.id, is_active=True)
    owner = User(email="owner@caredesk.ai", password_hash="x", full_name="Chủ",
                 role="owner", clinic_id=clinic.id, is_active=True)
    db.add_all([doctor, owner])
    db.commit()
    return {"clinic": clinic, "branch": branch, "doctor": doctor, "owner": owner}


@pytest.fixture
def client(db, setup):
    from backend.app.api.deps import verify_owner
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[verify_owner] = lambda: setup["owner"]
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _shift(client, setup, start, end):
    return client.post("/api/v1/clinic/schedules", json={
        "doctor_id": setup["doctor"].id, "branch_id": setup["branch"].id,
        "day_of_week": (datetime.date.today() + datetime.timedelta(days=1)).weekday(),
        "start_time": start, "end_time": end,
    })


# --- what a clinic can already do --------------------------------------------

def test_an_evening_shift_produces_evening_slots(client, db, setup):
    """The question behind "why can't I pick 19:00": nothing caps the hours, the
    clinic just has to have a shift covering them."""
    assert _shift(client, setup, "18:00", "22:00").status_code == 200

    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    times = get_available_slots(db, setup["doctor"].id, tomorrow, 30)

    assert times, "ca tối không sinh ra khung giờ nào"
    assert min(times) == datetime.time(18, 0)
    assert max(times) == datetime.time(21, 30)


def test_a_doctor_can_hold_two_shifts_in_one_day(client, db, setup):
    """Morning and evening with the lunch and afternoon closed — the shape most
    clinics that open late actually use."""
    assert _shift(client, setup, "08:00", "12:00").status_code == 200
    assert _shift(client, setup, "18:00", "22:00").status_code == 200

    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    times = get_available_slots(db, setup["doctor"].id, tomorrow, 30)

    assert datetime.time(9, 0) in times
    assert datetime.time(19, 0) in times
    assert datetime.time(15, 0) not in times, "giờ đóng cửa vẫn nhận đặt lịch"


def test_round_the_clock_is_expressible(client, db, setup):
    """A 24h clinic is one row, not a special case."""
    assert _shift(client, setup, "00:00", "23:59").status_code == 200

    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    times = get_available_slots(db, setup["doctor"].id, tomorrow, 30)

    assert datetime.time(2, 0) in times and datetime.time(23, 0) in times


# --- the shift that booked nobody --------------------------------------------

def test_an_overnight_shift_is_refused_with_a_way_out(client, setup):
    """It used to be accepted and then generate zero slots for ever. Refusing it
    is only half the fix — the message has to say how to enter a night shift,
    or the clinic concludes the product cannot do nights at all."""
    response = _shift(client, setup, "22:00", "02:00")

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "qua đêm" in detail and "22:00" in detail, detail


def test_a_zero_length_shift_is_refused(client, setup):
    assert _shift(client, setup, "09:00", "09:00").status_code == 400


def test_the_guard_is_on_the_api_not_only_the_form(client, db, setup):
    """The browser form checked this; the endpoint did not. Anything that is not
    a browser — an integration, a script, a future mobile app — could still
    write a shift that quietly books nobody."""
    _shift(client, setup, "23:00", "05:00")

    assert db.query(WorkingSchedule).count() == 0
