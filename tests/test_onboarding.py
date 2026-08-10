"""Setup must finish before a clinic can take real patients.

The gate that matters is the working schedule. A landing page published without
one greets patients with "hiện chưa có khung giờ trống" — the worst possible
first impression, and one the clinic blames on the AI rather than on their own
half-finished setup.
"""
import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.api.endpoints.onboarding import (
    BaselineIn, complete_onboarding, onboarding_status, save_baseline,
)
from backend.app.core.database import Base
from backend.app.models.models import (
    Branch, Clinic, Doctor, Service, User, WorkingSchedule,
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
def fresh(db):
    """A clinic exactly as self-registration leaves it: named, and nothing else."""
    clinic = Clinic(name="Phòng khám mới", address="1 A", phone="0900000000",
                    slug="pk-moi", is_active=True, landing_enabled=False)
    db.add(clinic)
    db.flush()
    owner = User(clinic_id=clinic.id, email="o@x.vn", password_hash="x",
                 full_name="Chủ", role="owner", is_active=True)
    db.add(owner)
    db.commit()
    return clinic, owner


def _finish_setup(db, clinic, with_schedule=True):
    branch = Branch(clinic_id=clinic.id, name="CS1", address="1 A",
                    working_hours="08:00 - 20:00", is_active=True)
    db.add(branch)
    db.flush()
    db.add(Service(clinic_id=clinic.id, name="Tri mun", price=500000, duration_minutes=30))
    doctor = Doctor(clinic_id=clinic.id, name="BS A", branch_id=branch.id, is_active=True)
    db.add(doctor)
    db.flush()
    if with_schedule:
        db.add(WorkingSchedule(doctor_id=doctor.id, branch_id=branch.id, day_of_week=0,
                               start_time=datetime.time(8, 0), end_time=datetime.time(17, 0)))
    db.commit()


def test_a_brand_new_clinic_cannot_go_live(db, fresh):
    clinic, owner = fresh
    status = onboarding_status(db=db, current_user=owner)

    assert status["can_go_live"] is False
    assert status["next"] == "hours", "địa chỉ/điện thoại đã có, còn thiếu cơ sở & giờ"
    assert clinic.landing_enabled is False


def test_the_missing_step_is_named_not_just_flagged(db, fresh):
    clinic, owner = fresh
    _finish_setup(db, clinic, with_schedule=False)

    status = onboarding_status(db=db, current_user=owner)
    unfinished = [s["key"] for s in status["steps"] if not s["done"]]
    assert "doctors" in unfinished
    assert status["can_go_live"] is False


def test_going_live_without_a_working_schedule_is_refused(db, fresh):
    clinic, owner = fresh
    _finish_setup(db, clinic, with_schedule=False)

    with pytest.raises(HTTPException) as exc:
        complete_onboarding(db=db, current_user=owner)

    assert exc.value.status_code == 409
    assert "Bác sĩ và lịch làm việc" in exc.value.detail
    db.refresh(clinic)
    assert clinic.landing_enabled is False, "link công khai vẫn phải đóng"


def test_a_complete_setup_opens_the_public_link(db, fresh):
    clinic, owner = fresh
    _finish_setup(db, clinic)

    result = complete_onboarding(db=db, current_user=owner)

    db.refresh(clinic)
    assert clinic.landing_enabled is True
    assert clinic.onboarding_completed_at is not None
    assert result["slug"] == "pk-moi"


def test_progress_reflects_data_not_a_stored_counter(db, fresh):
    """Filling something in from another screen counts; deleting it un-counts."""
    clinic, owner = fresh
    _finish_setup(db, clinic)
    assert onboarding_status(db=db, current_user=owner)["can_go_live"] is True

    db.query(WorkingSchedule).delete()
    db.commit()
    assert onboarding_status(db=db, current_user=owner)["can_go_live"] is False


# --- the baseline, which is what makes the pilot measurable ------------------

def test_the_baseline_is_stored_with_a_timestamp(db, fresh):
    clinic, owner = fresh
    save_baseline(body=BaselineIn(monthly_bookings=120, no_show_percent=25,
                                  daily_price_asks=15),
                  db=db, current_user=owner)

    db.refresh(clinic)
    assert clinic.baseline_monthly_bookings == 120
    assert clinic.baseline_no_show_percent == 25
    assert clinic.baseline_captured_at is not None


def test_the_baseline_does_not_block_going_live(db, fresh):
    """It is a question, not configuration — a clinic that skips it still works."""
    clinic, owner = fresh
    _finish_setup(db, clinic)

    status = onboarding_status(db=db, current_user=owner)
    baseline_step = next(s for s in status["steps"] if s["key"] == "baseline")
    assert baseline_step["done"] is False
    assert status["can_go_live"] is True


def test_a_simulated_channel_is_called_out_as_such(db, fresh, monkeypatch):
    """"Integration works but nothing reaches a patient" is a different problem
    from "nothing is set up", and it needs a different instruction. CareDesk has
    no business licence of its own, so a test OA is where every pilot starts —
    and this is the warning that stops one shipping in that state."""
    from backend.app.api.endpoints.clinic import get_readiness
    from backend.app.services import channel_gateway

    clinic, owner = fresh
    _finish_setup(db, clinic)
    monkeypatch.setattr(channel_gateway.settings, "SMS_PROVIDER", "mock", raising=False)

    codes = {b["code"]: b for b in get_readiness(db=db, current_user=owner)["blockers"]}
    assert "simulated_channel" in codes
    assert codes["simulated_channel"]["severity"] == "critical"
    assert "KHÔNG tới bệnh nhân thật" in codes["simulated_channel"]["message"]
    assert "no_phone_channel" not in codes, "một vấn đề, một cảnh báo"


def test_email_only_is_reported_honestly(db, fresh, monkeypatch):
    """Not "reminders are on" — Vietnamese patients do not read email reminders."""
    from backend.app.api.endpoints.clinic import get_readiness
    from backend.app.services import channel_gateway

    clinic, owner = fresh
    _finish_setup(db, clinic)
    monkeypatch.setattr(channel_gateway.settings, "SMS_PROVIDER", "", raising=False)
    monkeypatch.setattr(channel_gateway.settings, "SMTP_USER", "u", raising=False)
    monkeypatch.setattr(channel_gateway.settings, "SMTP_PASSWORD", "p", raising=False)

    codes = {b["code"]: b for b in get_readiness(db=db, current_user=owner)["blockers"]}
    assert codes["no_phone_channel"]["severity"] == "critical"
    assert "qua email" in codes["no_phone_channel"]["message"]


def test_an_impossible_baseline_is_refused(db, fresh):
    """A no-show rate over 100% means a typo, and a wrong baseline is worse than
    none — every later comparison inherits it."""
    with pytest.raises(Exception):
        BaselineIn(no_show_percent=250)
