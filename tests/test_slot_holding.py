"""A slot a patient is paying for must not be sold to someone else.

The failure this guards against is not theoretical: `awaiting_deposit` was
missing from the "occupied" set, so the sequence was

    khách A chốt 10:00 -> awaiting_deposit -> mở app ngân hàng
    khách B hỏi        -> AI trả lời 10:00 còn trống
    khách A trả tiền   -> hai người cùng một khung giờ
"""
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.booking_rules import (
    SLOT_HOLDING_STATUSES, STATUS_AWAITING_DEPOSIT, STATUS_CANCELLED,
    STATUS_CONFIRMED,
)
from backend.app.core.database import Base
from backend.app.models.models import (
    Appointment, Branch, Clinic, Doctor, PatientLead, Payment, Service,
    WorkingSchedule,
)
from backend.app.services.ai_engine import get_available_slots
from backend.app.services.payment_gateway import (
    hold_for_deposit, mark_paid, release_expired_holds,
)

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
def setup(db):
    clinic = Clinic(name="CareDesk", is_active=True, deposit_amount=200000)
    db.add(clinic)
    db.flush()
    branch = Branch(clinic_id=clinic.id, name="CS1", address="1 A", is_active=True)
    service = Service(clinic_id=clinic.id, name="Tri mun", price=500000, duration_minutes=30)
    doctor = Doctor(clinic_id=clinic.id, name="BS A", is_active=True)
    db.add_all([branch, service, doctor])
    db.flush()
    doctor.branch_id = branch.id
    for day in range(7):
        db.add(WorkingSchedule(doctor_id=doctor.id, branch_id=branch.id, day_of_week=day,
                               start_time=datetime.time(8, 0), end_time=datetime.time(17, 0)))
    patient = PatientLead(clinic_id=clinic.id, full_name="Khach A", phone="0900000001",
                          consent_given=True)
    db.add(patient)
    db.commit()
    return {"clinic": clinic, "branch": branch, "service": service,
            "doctor": doctor, "patient": patient}


def _tomorrow_at(hour):
    d = datetime.date.today() + datetime.timedelta(days=1)
    return datetime.datetime.combine(d, datetime.time(hour, 0))


def _book(db, s, hour, status, hold_expires_at=None):
    start = _tomorrow_at(hour)
    appt = Appointment(
        clinic_id=s["clinic"].id, branch_id=s["branch"].id, service_id=s["service"].id,
        doctor_id=s["doctor"].id, patient_id=s["patient"].id, status=status,
        start_time=start, end_time=start + datetime.timedelta(minutes=30),
        hold_expires_at=hold_expires_at,
    )
    db.add(appt)
    db.commit()
    return appt


def _free_at(db, s, hour):
    slots = get_available_slots(db, s["doctor"].id, _tomorrow_at(hour).date(), 30)
    return datetime.time(hour, 0) in slots


# --- the regression ----------------------------------------------------------

def test_a_slot_awaiting_deposit_is_not_offered_to_anyone_else(db, setup):
    assert _free_at(db, setup, 10) is True
    _book(db, setup, 10, STATUS_AWAITING_DEPOSIT,
          hold_expires_at=datetime.datetime.now() + datetime.timedelta(minutes=15))
    assert _free_at(db, setup, 10) is False, (
        "khách đang đi chuyển tiền vẫn giữ khung giờ này"
    )


def test_awaiting_deposit_is_in_the_occupied_set(db):
    assert STATUS_AWAITING_DEPOSIT in SLOT_HOLDING_STATUSES
    assert STATUS_CANCELLED not in SLOT_HOLDING_STATUSES


def test_confirmed_still_blocks_and_cancelled_still_frees(db, setup):
    _book(db, setup, 11, STATUS_CONFIRMED)
    assert _free_at(db, setup, 11) is False

    appt = _book(db, setup, 13, STATUS_CONFIRMED)
    appt.status = STATUS_CANCELLED
    db.commit()
    assert _free_at(db, setup, 13) is True


# --- the deadline that keeps the hold from becoming a lock -------------------

def test_an_expired_hold_stops_blocking_immediately(db, setup):
    """Filtered in the slot query too, not only by the scheduler — otherwise a
    patient asking between ticks is told a free slot is taken."""
    _book(db, setup, 14, STATUS_AWAITING_DEPOSIT,
          hold_expires_at=datetime.datetime.now() - datetime.timedelta(minutes=1))
    assert _free_at(db, setup, 14) is True


def test_release_expired_holds_cancels_and_frees(db, setup):
    appt = _book(db, setup, 15, STATUS_AWAITING_DEPOSIT,
                 hold_expires_at=datetime.datetime.now() - datetime.timedelta(minutes=1))
    assert release_expired_holds(db) == 1
    db.refresh(appt)
    assert appt.status == STATUS_CANCELLED
    assert "quá hạn đặt cọc" in appt.note
    assert _free_at(db, setup, 15) is True


def test_a_live_hold_is_left_alone(db, setup):
    appt = _book(db, setup, 16, STATUS_AWAITING_DEPOSIT,
                 hold_expires_at=datetime.datetime.now() + datetime.timedelta(minutes=10))
    assert release_expired_holds(db) == 0
    db.refresh(appt)
    assert appt.status == STATUS_AWAITING_DEPOSIT


# --- deposit wiring (previously create_deposit_payment was never called) -----

def test_hold_for_deposit_creates_a_payment_and_holds_the_slot(db, setup):
    appt = _book(db, setup, 9, "pending")
    payment, url = hold_for_deposit(db, appt, setup["clinic"])
    db.commit()

    assert payment is not None and url
    assert payment.amount == 200000
    assert appt.status == STATUS_AWAITING_DEPOSIT
    assert appt.hold_expires_at is not None
    assert db.query(Payment).count() == 1


def test_no_deposit_configured_means_no_hold(db, setup):
    setup["clinic"].deposit_amount = 0
    db.commit()
    appt = _book(db, setup, 9, "pending")

    payment, url = hold_for_deposit(db, appt, setup["clinic"])
    assert payment is None and url is None
    assert appt.status == "pending"
    assert appt.hold_expires_at is None


def test_paying_the_deposit_confirms_and_clears_the_deadline(db, setup):
    appt = _book(db, setup, 9, "pending")
    payment, _ = hold_for_deposit(db, appt, setup["clinic"])
    db.commit()

    mark_paid(db, payment)
    db.refresh(appt)
    assert appt.status == STATUS_CONFIRMED
    assert appt.hold_expires_at is None, "a paid booking is no longer a timed hold"
    assert _free_at(db, setup, 9) is False
