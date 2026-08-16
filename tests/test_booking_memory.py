"""What the patient said, remembered by whichever half is listening.

This product has two brains. The model carries the conversation; the state
machine carries the booking. They did not share.

So a patient could say "đặt lịch trị mụn với bác sĩ Trần Minh C tại Quận 10
sáng thứ 3 tuần sau", have the model repeat it all back, confirm it — and then
be asked "Bạn muốn khám vào ngày nào ạ?", because every detail had been given
on turns the model answered and none of it ever reached the state machine.

From the other side of the screen that is simply an assistant that does not
remember, asking the same questions and never getting to an answer.
"""
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core import clock
from backend.app.core.database import Base
from backend.app.models.models import (
    BookingRequest, Branch, Clinic, Conversation, Doctor, PatientLead, Service,
    WorkingSchedule,
)
from backend.app.services.booking_flow import _parse_date, handle_booking

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
    clinic = Clinic(name="CareDesk", is_active=True)
    db.add(clinic)
    db.flush()
    branch = Branch(clinic_id=clinic.id, name="Quận 10", address="123 Ba Tháng Hai",
                    is_active=True)
    db.add(branch)
    db.flush()
    service = Service(clinic_id=clinic.id, name="Điều trị mụn Chuẩn Y Khoa",
                      price=450000, duration_minutes=45)
    doctor = Doctor(clinic_id=clinic.id, name="Bác sĩ Trần Minh C",
                    branch_id=branch.id, is_active=True)
    patient = PatientLead(clinic_id=clinic.id, full_name="phương uyên", phone="0912202303")
    db.add_all([service, doctor, patient])
    db.flush()
    for day in range(7):
        db.add(WorkingSchedule(doctor_id=doctor.id, branch_id=branch.id, day_of_week=day,
                               start_time=datetime.time(8, 0), end_time=datetime.time(18, 0)))
    conv = Conversation(clinic_id=clinic.id, patient_id=patient.id, branch_id=branch.id)
    db.add(conv)
    db.commit()
    return {"clinic": clinic, "service": service, "doctor": doctor, "conv": conv}


# --- memory across turns the model answers ------------------------------------

def test_details_given_before_booking_intent_are_kept(db, setup):
    """No booking keyword, so the flow declines the turn — but it must not throw
    away what it just read."""
    assert handle_booking(db, setup["conv"], "bác sĩ Trần Minh C có trị mụn không ạ") is None
    db.refresh(setup["conv"])

    state = setup["conv"].booking_state or {}
    assert state.get("doctor_id") == setup["doctor"].id
    assert state.get("service_id") == setup["service"].id
    # Remembering is not intent: nothing has been started.
    assert not state.get("active")


def test_activation_does_not_wipe_what_was_remembered(db, setup):
    """The line that reset the state on activation is what made the flow ask for
    a service and a date it had already been told."""
    handle_booking(db, setup["conv"], "bác sĩ Trần Minh C trị mụn thế nào ạ")
    reply = handle_booking(db, setup["conv"], "vậy đặt lịch giúp tôi")
    db.refresh(setup["conv"])

    state = setup["conv"].booking_state
    assert state["service_id"] == setup["service"].id, "quên dịch vụ khách đã nói"
    assert state["doctor_id"] == setup["doctor"].id, "quên bác sĩ khách đã chọn"
    assert "Trần Minh C" in reply


def test_the_conversation_from_the_report(db, setup):
    """The exact sequence: everything said up front, then a time, and the flow
    asking for the date as though nothing had happened."""
    handle_booking(db, setup["conv"],
                   "tôi muốn đặt lịch trị mụn với bác sĩ Trần Minh C sáng thứ 3 tuần sau")
    reply = handle_booking(db, setup["conv"], "9h nhé")

    assert "ngày nào" not in (reply or "").lower(), \
        "vẫn hỏi lại ngày dù khách đã nói 'thứ 3 tuần sau'"

    # Nothing left to ask: it had the service, the doctor, the day and now the
    # time, so the request is written instead of the conversation going round.
    request = db.query(BookingRequest).first()
    assert request is not None, "hỏi vòng vo mà không chốt được"
    assert request.doctor_id == setup["doctor"].id
    assert request.preferred_at.weekday() == 1, "không phải thứ 3"
    assert request.preferred_at.date() > clock.today() + datetime.timedelta(days=1), \
        "'tuần sau' bị hiểu thành tuần này"
    assert request.preferred_at.strftime("%H:%M") == "09:00"


def test_a_question_mid_flow_still_records_a_date(db, setup):
    """The fall-through that hands the turn to the model has to keep the date the
    patient slipped into the same sentence."""
    handle_booking(db, setup["conv"], "đặt lịch trị mụn")
    handle_booking(db, setup["conv"], "thứ 5 tuần sau có đau không ạ")
    db.refresh(setup["conv"])

    assert setup["conv"].booking_state.get("date")


# --- "tuần sau" means next week ------------------------------------------------

def test_next_week_is_next_week():
    """Booking someone a week early is a missed appointment, not a rounding
    error: they turn up to a clinic that is not expecting them."""
    today = clock.today()
    this_tuesday = _parse_date("thứ 3")
    next_tuesday = _parse_date("thứ 3 tuần sau")

    assert datetime.date.fromisoformat(next_tuesday) - datetime.date.fromisoformat(this_tuesday) \
        == datetime.timedelta(days=7)
    assert datetime.date.fromisoformat(next_tuesday) > today


def test_a_weekday_naming_today_means_next_week():
    """"thứ 3" said on a Tuesday is not this morning — that slot is half gone."""
    today = clock.today()
    same_weekday = ["thứ 2", "thứ 3", "thứ 4", "thứ 5", "thứ 6", "thứ 7", "chủ nhật"][today.weekday()]

    parsed = datetime.date.fromisoformat(_parse_date(same_weekday))

    assert parsed == today + datetime.timedelta(days=7)


def test_next_week_alone_still_gives_a_date():
    assert _parse_date("tuần sau nhé") == (clock.today() + datetime.timedelta(days=7)).isoformat()


# --- confirming ---------------------------------------------------------------

def test_dung_is_agreement(db, setup):
    """"đúng," was the patient's confirmation and counted as nothing, so the
    conversation went round again."""
    from backend.app.services.booking_flow import _is_affirmative

    assert _is_affirmative("dung,") is True
    assert _is_affirmative("dung roi ban") is True
    # Still not a blanket match: this is a question, not consent.
    assert _is_affirmative("dung cho toi hoi them mot chut nua nhe") is False


def test_yes_accepts_the_offer_of_another_doctor(db, setup):
    """The assistant asks "để tôi xếp bác sĩ khác không ạ?" — and "đúng" used to
    answer nothing, so it asked again. And again."""
    db.query(WorkingSchedule).filter(
        WorkingSchedule.doctor_id == setup["doctor"].id).delete()
    other = Doctor(clinic_id=setup["clinic"].id, name="Bác sĩ Lê Thị B",
                   branch_id=setup["conv"].branch_id, is_active=True)
    db.add(other)
    db.flush()
    for day in range(7):
        db.add(WorkingSchedule(doctor_id=other.id, branch_id=setup["conv"].branch_id,
                               day_of_week=day, start_time=datetime.time(8, 0),
                               end_time=datetime.time(18, 0)))
    db.commit()

    handle_booking(db, setup["conv"], "đặt lịch trị mụn với bác sĩ Trần Minh C")
    offer = handle_booking(db, setup["conv"], "thứ 3 tuần sau")
    assert "bác sĩ khác" in offer.lower(), offer

    reply = handle_booking(db, setup["conv"], "đúng,")

    assert "khung giờ" in reply.lower(), f"nói 'đúng' mà vẫn hỏi lại: {reply}"
    db.refresh(setup["conv"])
    assert not setup["conv"].booking_state.get("doctor_requested")
