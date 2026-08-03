import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.app.core.database import Base
from backend.app.models.models import (
    Clinic, Branch, Service, Doctor, WorkingSchedule, PatientLead, Conversation, Appointment, BookingRequest
)

from backend.app.services.ai_engine import process_chat_message

engine = create_engine("sqlite:///:memory:")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    clinic = Clinic(name="PK Test", plan="pro", ai_quota_monthly=1000)
    db.add(clinic)
    db.commit()

    branch = Branch(clinic_id=clinic.id, name="CN Test", address="1 Test St")
    db.add(branch)
    db.commit()

    service = Service(
        clinic_id=clinic.id, name="Điều trị mụn Chuẩn Y Khoa",
        price=450000, duration_minutes=75
    )
    db.add(service)
    db.commit()

    doctor = Doctor(clinic_id=clinic.id, name="BS Test", branch_id=branch.id, is_active=True)
    db.add(doctor)
    db.commit()

    # Doctor works every day 08:00 - 18:00 so any test date has slots
    for day in range(7):
        db.add(WorkingSchedule(
            doctor_id=doctor.id, branch_id=branch.id, day_of_week=day,
            start_time=datetime.time(8, 0), end_time=datetime.time(18, 0)
        ))
    db.commit()

    lead = PatientLead(clinic_id=clinic.id, full_name="Nguyễn Thị Test", phone="0901234567", consent_given=True)
    db.add(lead)
    db.commit()

    conv = Conversation(clinic_id=clinic.id, patient_id=lead.id, channel="web", status="bot_active")
    db.add(conv)
    db.commit()

    yield db, conv

    db.close()
    Base.metadata.drop_all(bind=engine)


def test_booking_end_to_end(db_session):
    """AI submits a request: intent -> date -> slot choice -> BookingRequest created."""



    db, conv = db_session

    # 1. Intent with service; name/phone auto-filled from the lead -> bot asks for a date
    res, handoff = process_chat_message(db, conv.id, "Tôi muốn đặt lịch trị mụn")
    assert handoff is False
    assert "ngày nào" in res.lower()
    assert "họ tên" in res.lower() and "số điện thoại" in res.lower()

    # 2. Give a date -> bot proposes real free slots
    res, handoff = process_chat_message(db, conv.id, "ngày mai nhé")
    assert handoff is False
    assert "khung giờ" in res.lower()
    db.refresh(conv)
    proposed = conv.booking_state.get("proposed_slots")
    assert proposed and len(proposed) >= 1

        # 3. Choose slot #1 -> only a request is created; staff must create the appointment.

    res, handoff = process_chat_message(db, conv.id, "1")
    assert handoff is False
    assert "yêu cầu đặt lịch" in res.lower()
    assert "chưa phải là lịch hẹn chính thức" in res.lower()

    request = db.query(BookingRequest).first()
    assert request is not None
    assert request.status == "requested"
    assert request.preferred_time.endswith(proposed[0])
    assert request.patient_id == conv.patient_id
    assert db.query(Appointment).count() == 0



def test_booking_not_triggered_by_faq(db_session):
    """A price question must NOT enter the booking flow."""
    db, conv = db_session
    res, handoff = process_chat_message(db, conv.id, "Trị mụn giá bao nhiêu vậy?")
    assert handoff is False
    assert db.query(Appointment).count() == 0
    db.refresh(conv)
    assert not (conv.booking_state or {}).get("active")


def test_booking_cancel_flow(db_session):
    db, conv = db_session
    process_chat_message(db, conv.id, "Tôi muốn đặt lịch trị mụn")
    res, _ = process_chat_message(db, conv.id, "thôi không đặt nữa")
    assert "hủy" in res.lower()
    db.refresh(conv)
    assert conv.booking_state.get("active") is False
    assert db.query(Appointment).count() == 0


def test_quota_exceeded_triggers_handoff(db_session):
    """When the clinic exhausts its monthly AI quota, the bot hands off."""
    db, conv = db_session
    clinic = db.query(Clinic).first()
    clinic.ai_quota_monthly = 0
    db.commit()

    res, handoff = process_chat_message(db, conv.id, "Xin chào")
    assert handoff is True
    assert "giới hạn" in res.lower()
    db.refresh(conv)
    assert conv.status == "handoff_requested"
