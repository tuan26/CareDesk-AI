"""A question asked during a booking must still be answered.

The reported symptom was "AI trả lời không chuẩn". The cause was not the model:
once the booking state machine was active it answered every message with the
next form field, so

    "Laser CO2 có đau không?"  ->  "Bạn muốn đặt lịch vào ngày nào ạ?"

There was a guard for this, but it required a word from a list — giá, địa chỉ,
mấy giờ. "Có đau không" and "bao lâu thì khỏi" were not on it, so the two
questions patients ask most about an aesthetic procedure were treated as
booking input.

The list is gone. A message carrying no booking information is not advancing
the booking, whatever it is, so the assistant answers it instead.
"""
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models.models import (
    Branch, Clinic, Conversation, Doctor, PatientLead, Service, WorkingSchedule,
)
from backend.app.services.booking_flow import handle_booking

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
def conv(db):
    """A booking already under way: service chosen, waiting on a date."""
    clinic = Clinic(name="CareDesk", is_active=True)
    db.add(clinic)
    db.flush()
    branch = Branch(clinic_id=clinic.id, name="CS1", address="1 Lê Lợi", is_active=True)
    db.add(branch)
    db.flush()
    service = Service(clinic_id=clinic.id, name="Laser Fractional CO2 trị sẹo rỗ",
                      price=1200000, duration_minutes=60)
    doctor = Doctor(clinic_id=clinic.id, name="BS An", branch_id=branch.id, is_active=True)
    patient = PatientLead(clinic_id=clinic.id, full_name="Chị Hoa", phone="0901234567")
    db.add_all([service, doctor, patient])
    db.flush()
    for day in range(7):
        db.add(WorkingSchedule(doctor_id=doctor.id, branch_id=branch.id, day_of_week=day,
                               start_time=datetime.time(8, 0), end_time=datetime.time(17, 0)))
    c = Conversation(clinic_id=clinic.id, patient_id=patient.id, branch_id=branch.id,
                     booking_state={"active": True, "service_id": service.id,
                                    "full_name": "Chị Hoa", "phone": "0901234567"})
    db.add(c)
    db.commit()
    return c


# --- the questions that were being swallowed ---------------------------------

@pytest.mark.parametrize("question", [
    "Laser CO2 có đau không?",
    "Bao lâu thì hết mụn?",
    "Làm xong có phải kiêng nắng không?",
    "Có cần nghỉ dưỡng mấy ngày không?",
    "Bác sĩ nào làm cho tôi vậy?",
])
def test_a_question_mid_booking_falls_through_to_the_assistant(db, conv, question):
    """None of these carry booking information, so none of them are an answer to
    "ngày nào ạ" — and replying with that question again is the behaviour the
    patient reported as the assistant not listening."""
    assert handle_booking(db, conv, question) is None, question


def test_the_booking_state_survives_the_question(db, conv):
    """Falling through must not lose the half-collected booking: the patient
    asks, gets an answer, and carries on where they left off."""
    handle_booking(db, conv, "Laser CO2 có đau không?")
    db.refresh(conv)

    assert conv.booking_state["active"] is True
    assert conv.booking_state["service_id"] is not None


# --- and the messages that really are booking input --------------------------

@pytest.mark.parametrize("message", [
    "ngày mai nhé",
    "thứ 7 được không",
    "0987654321",
    "vâng ạ",
    "ok bạn",
])
def test_real_booking_input_is_still_handled(db, conv, message):
    """The fall-through must not swallow the flow itself. An affirmative counts:
    "vâng ạ" carries no date and no service, but it is plainly an answer."""
    assert handle_booking(db, conv, message) is not None, message


def test_a_numbered_slot_choice_is_not_mistaken_for_chatter(db, conv):
    """"2" carries no date, no phone and no service — but when slots have been
    proposed it is the whole answer."""
    conv.booking_state = {**conv.booking_state,
                          "date": (datetime.date.today() + datetime.timedelta(days=1)).isoformat(),
                          "proposed_slots": ["09:00", "10:00", "11:00"]}
    db.commit()

    assert handle_booking(db, conv, "2") is not None


# --- nothing claims a booking that does not exist ----------------------------

def test_the_flow_does_not_say_a_booking_is_recorded_before_it_is(db, conv):
    """"Đã ghi nhận" while still asking for a date is the same lie the model is
    forbidden to tell — the patient stops looking and turns up unannounced."""
    reply = handle_booking(db, conv, "đặt lịch giúp tôi")

    assert reply is not None
    assert "đã ghi nhận" not in reply.lower(), reply
