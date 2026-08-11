"""A doctor on leave must not be bookable.

WorkingSchedule says which weekdays a doctor works and is true forever once
entered. With no way to record an exception, the AI books straight through Tết
and the patient arrives at a locked door — the kind of incident that gets the
assistant switched off permanently. So this is treated as a booking-correctness
bug, not a convenience feature.
"""
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models.models import (
    Branch, Clinic, Doctor, DoctorTimeOff, WorkingSchedule,
)
from backend.app.services.ai_engine import get_available_slots, time_off_for
from backend.app.services.booking_flow import _pick_doctor_and_slots

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
    """Two doctors at one branch, both working every day 08:00-17:00."""
    clinic = Clinic(name="CareDesk", is_active=True)
    db.add(clinic)
    db.flush()
    branch = Branch(clinic_id=clinic.id, name="CS1", address="1 A", is_active=True)
    db.add(branch)
    db.flush()
    d1 = Doctor(clinic_id=clinic.id, name="BS Mot", branch_id=branch.id, is_active=True)
    d2 = Doctor(clinic_id=clinic.id, name="BS Hai", branch_id=branch.id, is_active=True)
    db.add_all([d1, d2])
    db.flush()
    for day in range(7):
        for d in (d1, d2):
            db.add(WorkingSchedule(doctor_id=d.id, branch_id=branch.id, day_of_week=day,
                                   start_time=datetime.time(8, 0),
                                   end_time=datetime.time(17, 0)))
    db.commit()
    return {"clinic": clinic, "branch": branch, "d1": d1, "d2": d2}


def _tomorrow():
    return datetime.date.today() + datetime.timedelta(days=1)


def _slots(db, doctor, day=None):
    return get_available_slots(db, doctor.id, day or _tomorrow(), 30)


# --- the regression ----------------------------------------------------------

def test_a_doctor_on_leave_has_no_slots(db, setup):
    assert _slots(db, setup["d1"]), "chưa nghỉ thì phải có khung giờ"

    db.add(DoctorTimeOff(clinic_id=setup["clinic"].id, doctor_id=setup["d1"].id,
                         start_date=_tomorrow(), end_date=_tomorrow(),
                         reason="Nghỉ phép"))
    db.commit()

    assert _slots(db, setup["d1"]) == []


def test_leave_does_not_affect_the_other_doctor(db, setup):
    db.add(DoctorTimeOff(clinic_id=setup["clinic"].id, doctor_id=setup["d1"].id,
                         start_date=_tomorrow(), end_date=_tomorrow()))
    db.commit()

    assert _slots(db, setup["d1"]) == []
    assert _slots(db, setup["d2"]), "bác sĩ khác vẫn nhận lịch bình thường"


def test_a_clinic_wide_closure_covers_every_doctor(db, setup):
    """Tết is entered once, not once per doctor — that is exactly how a doctor
    gets forgotten and keeps taking bookings."""
    db.add(DoctorTimeOff(clinic_id=setup["clinic"].id, doctor_id=None,
                         start_date=_tomorrow(), end_date=_tomorrow(),
                         reason="Nghỉ Tết"))
    db.commit()

    assert _slots(db, setup["d1"]) == []
    assert _slots(db, setup["d2"]) == []


def test_a_multi_day_range_is_inclusive_at_both_ends(db, setup):
    start = _tomorrow()
    end = start + datetime.timedelta(days=4)
    db.add(DoctorTimeOff(clinic_id=setup["clinic"].id, doctor_id=setup["d1"].id,
                         start_date=start, end_date=end))
    db.commit()

    for offset in range(5):
        assert _slots(db, setup["d1"], start + datetime.timedelta(days=offset)) == [], \
            f"ngày thứ {offset} trong kỳ nghỉ vẫn nhận lịch"
    assert _slots(db, setup["d1"], end + datetime.timedelta(days=1)), \
        "ngày sau kỳ nghỉ phải mở lại"


def test_a_day_before_the_leave_is_untouched(db, setup):
    db.add(DoctorTimeOff(clinic_id=setup["clinic"].id, doctor_id=setup["d1"].id,
                         start_date=_tomorrow() + datetime.timedelta(days=3),
                         end_date=_tomorrow() + datetime.timedelta(days=5)))
    db.commit()
    assert _slots(db, setup["d1"])


# --- half days ---------------------------------------------------------------

def test_a_half_day_blocks_only_its_own_hours(db, setup):
    """"Nghỉ chiều thứ 5" must not cost the whole day of bookings."""
    db.add(DoctorTimeOff(clinic_id=setup["clinic"].id, doctor_id=setup["d1"].id,
                         start_date=_tomorrow(), end_date=_tomorrow(),
                         start_time=datetime.time(13, 0), end_time=datetime.time(17, 0),
                         reason="Nghỉ chiều"))
    db.commit()

    slots = _slots(db, setup["d1"])
    assert slots, "buổi sáng vẫn phải đặt được"
    assert all(s < datetime.time(13, 0) for s in slots), \
        f"còn khung giờ trong buổi nghỉ: {[str(s) for s in slots]}"


def test_a_half_day_at_the_start_leaves_the_afternoon(db, setup):
    db.add(DoctorTimeOff(clinic_id=setup["clinic"].id, doctor_id=setup["d1"].id,
                         start_date=_tomorrow(), end_date=_tomorrow(),
                         start_time=datetime.time(8, 0), end_time=datetime.time(12, 0)))
    db.commit()

    slots = _slots(db, setup["d1"])
    assert slots and all(s >= datetime.time(12, 0) for s in slots)


# --- the AI booking path, not just the slot function -------------------------

def test_the_booking_flow_skips_a_doctor_on_leave(db, setup):
    """_pick_doctor_and_slots walks the doctors — it must land on the one who is
    actually there, not the first one in the table."""
    db.add(DoctorTimeOff(clinic_id=setup["clinic"].id, doctor_id=setup["d1"].id,
                         start_date=_tomorrow(), end_date=_tomorrow()))
    db.commit()

    doctor, branch, slots = _pick_doctor_and_slots(
        db, setup["clinic"].id, _tomorrow(), 30, branch_id=setup["branch"].id)

    assert slots
    assert doctor.id == setup["d2"].id


def test_a_clinic_wide_closure_offers_nothing_at_all(db, setup):
    db.add(DoctorTimeOff(clinic_id=setup["clinic"].id, doctor_id=None,
                         start_date=_tomorrow(), end_date=_tomorrow()))
    db.commit()

    _, _, slots = _pick_doctor_and_slots(
        db, setup["clinic"].id, _tomorrow(), 30, branch_id=setup["branch"].id)
    assert slots == []


def test_time_off_lookup_includes_clinic_wide_rows(db, setup):
    db.add(DoctorTimeOff(clinic_id=setup["clinic"].id, doctor_id=None,
                         start_date=_tomorrow(), end_date=_tomorrow()))
    db.add(DoctorTimeOff(clinic_id=setup["clinic"].id, doctor_id=setup["d1"].id,
                         start_date=_tomorrow(), end_date=_tomorrow()))
    db.commit()

    assert len(time_off_for(db, setup["d1"].id, _tomorrow())) == 2
    assert len(time_off_for(db, setup["d2"].id, _tomorrow())) == 1


def test_another_clinics_leave_is_invisible(db, setup):
    """Multi-tenant isolation: one clinic's holiday must not close another's."""
    other = Clinic(name="Khac", is_active=True)
    db.add(other)
    db.flush()
    db.add(DoctorTimeOff(clinic_id=other.id, doctor_id=None,
                         start_date=_tomorrow(), end_date=_tomorrow()))
    db.commit()

    assert _slots(db, setup["d1"]), "phòng khám khác nghỉ không được ảnh hưởng"
