"""The AI must never tell a patient they are booked when they are not.

A real conversation reached "Mình đã ghi nhận thông tin đặt lịch Laser
Fractional CO2 vào sáng thứ 2..." while booking_requests was empty and
booking_state was NULL. Two separate faults produced it:

1. Intent matching required exact diacritics, so "đặt lich" — one missing dot —
   never woke the state machine, and the model answered the whole conversation
   on its own.
2. The model has no tool that can record a booking, so when it decided one had
   been made it simply said so. The patient stops looking, arrives on the day,
   and nobody at the clinic is expecting them.
"""
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models.models import (
    BookingRequest, Branch, Clinic, Conversation, Doctor, Message, PatientLead,
    Service, WorkingSchedule,
)
from backend.app.services import ai_engine
from backend.app.services.ai_engine import (
    BOOKING_CLAIM_PHRASES, BOOKING_TOKEN, process_chat_message,
)
from backend.app.services.booking_flow import (
    BOOKING_INTENT_KEYWORDS, strip_accents,
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


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    monkeypatch.setattr(ai_engine, "openai_client", None)


@pytest.fixture
def conv(db):
    clinic = Clinic(name="CareDesk", is_active=True)
    db.add(clinic)
    db.flush()
    branch = Branch(clinic_id=clinic.id, name="Bach Mai", address="1 A", is_active=True)
    db.add(branch)
    db.flush()
    service = Service(clinic_id=clinic.id, name="Laser Fractional CO2 trị sẹo rỗ",
                      price=1200000, duration_minutes=60)
    doctor = Doctor(clinic_id=clinic.id, name="BS An", branch_id=branch.id, is_active=True)
    db.add_all([service, doctor])
    db.flush()
    for day in range(7):
        db.add(WorkingSchedule(doctor_id=doctor.id, branch_id=branch.id, day_of_week=day,
                               start_time=datetime.time(8, 0), end_time=datetime.time(17, 0)))
    patient = PatientLead(clinic_id=clinic.id, full_name="Trịnh Kim Uyên",
                          phone="0878755588", consent_given=True)
    db.add(patient)
    db.flush()
    c = Conversation(clinic_id=clinic.id, patient_id=patient.id, branch_id=branch.id,
                     channel="web", status="bot_active")
    db.add(c)
    db.commit()
    return c


def _reply(text):
    return lambda db, clinic, msg, locale="vi": text


# --- fault 1: diacritics -----------------------------------------------------

def test_the_exact_message_that_failed_now_registers_intent():
    """Verbatim from the conversation that broke. "lich", not "lịch"."""
    folded = strip_accents("đặt lich vào thứ 2 tuần sau trong buổi sáng")
    assert any(k in folded for k in BOOKING_INTENT_KEYWORDS)


@pytest.mark.parametrize("message", [
    "đặt lịch ngày mai",
    "đặt lich vào thứ 2",
    "dat lich ngay mai",
    "DAT LICH GIUP MINH",
    "cho mình đặt hẹn với",
    "cho minh dat hen voi",
    "mình muốn hẹn khám",
    "book an appointment please",
])
def test_booking_intent_survives_however_it_is_typed(message):
    """Vietnamese is routinely typed without diacritics, and phones drop them."""
    folded = strip_accents(message)
    assert any(k in folded for k in BOOKING_INTENT_KEYWORDS), message


@pytest.mark.parametrize("message", [
    "Tôi muốn tư vấn gói làm đẹp da",
    "Laser Fractional CO2 trị sẹo rỗ",
    "giá bao nhiêu vậy",
    "có bác sĩ nào không",
])
def test_ordinary_questions_do_not_hijack_the_booking_flow(message):
    """Folding must not make the matcher so loose that browsing turns into a
    booking interrogation."""
    folded = strip_accents(message)
    assert not any(k in folded for k in BOOKING_INTENT_KEYWORDS), message


def test_accent_folding_handles_d_with_stroke():
    """"đ" has no combining form, so NFD alone leaves it and "đặt" never matches
    "dat"."""
    assert strip_accents("Đặt Lịch") == "dat lich"


# --- fault 2: the model claiming a booking it cannot make --------------------

def test_a_fabricated_booking_claim_is_replaced_not_delivered(db, conv, monkeypatch):
    """The exact failure: a confident confirmation with nothing behind it."""
    monkeypatch.setattr(ai_engine, "call_openai_gpt_mock", _reply(
        "Cảm ơn bạn Trịnh Kim Uyên. Mình đã ghi nhận thông tin đặt lịch Laser "
        "Fractional CO2 vào sáng thứ 2 tuần sau tại cơ sở Bạch Mai."))

    reply, is_handoff = process_chat_message(db, conv.id, "cam on")

    assert "đã ghi nhận" not in reply.lower(), "vẫn đang nói dối khách"
    assert "chưa gửi được yêu cầu đặt lịch" in reply.lower()
    assert is_handoff is True, "phải chuyển lễ tân, không để khách tưởng đã xong"

    db.refresh(conv)
    assert conv.status == "handoff_requested"


def test_the_fabrication_is_recorded_for_the_clinic_to_see(db, conv, monkeypatch):
    monkeypatch.setattr(ai_engine, "call_openai_gpt_mock",
                        _reply("Mình đã đặt lịch cho bạn rồi nhé."))
    process_chat_message(db, conv.id, "ok")

    msg = db.query(Message).filter(Message.sender == "bot").order_by(Message.id.desc()).first()
    assert msg.evaluation_metadata.get("fabricated_booking_claim") is True
    assert msg.evaluation_metadata.get("handoff_reason") == "fabricated_booking"


def test_the_same_sentence_is_allowed_once_a_request_really_exists(db, conv, monkeypatch):
    """The guard checks the database, not the wording — a genuine confirmation
    must still be deliverable."""
    db.add(BookingRequest(
        clinic_id=conv.clinic_id, conversation_id=conv.id, patient_id=conv.patient_id,
        service_or_need="Laser", full_name="Trịnh Kim Uyên",
        contact_method="phone", contact_value="0878755588", status="requested",
    ))
    db.commit()

    monkeypatch.setattr(ai_engine, "call_openai_gpt_mock",
                        _reply("Mình đã ghi nhận thông tin đặt lịch của bạn."))
    reply, is_handoff = process_chat_message(db, conv.id, "cam on")

    assert "đã ghi nhận" in reply.lower()
    assert is_handoff is False


def test_a_cancelled_request_does_not_excuse_the_claim(db, conv, monkeypatch):
    db.add(BookingRequest(
        clinic_id=conv.clinic_id, conversation_id=conv.id, patient_id=conv.patient_id,
        service_or_need="Laser", full_name="X", contact_method="phone",
        contact_value="0878755588", status="cancelled",
    ))
    db.commit()

    monkeypatch.setattr(ai_engine, "call_openai_gpt_mock",
                        _reply("Mình đã ghi nhận thông tin đặt lịch của bạn."))
    _, is_handoff = process_chat_message(db, conv.id, "cam on")
    assert is_handoff is True


def test_every_claim_phrase_is_caught(db, conv, monkeypatch):
    for phrase in BOOKING_CLAIM_PHRASES:
        monkeypatch.setattr(ai_engine, "call_openai_gpt_mock",
                            _reply(f"Dạ {phrase} nhé bạn."))
        reply, is_handoff = process_chat_message(db, conv.id, "ok")
        assert is_handoff is True, phrase
        assert phrase not in reply.lower(), phrase


# --- the model can hand the booking to the flow that can actually do it ------

def test_the_booking_token_activates_the_real_flow(db, conv, monkeypatch):
    """No keyword list covers every phrasing, so the model gets to raise its
    hand — and what it hands to is the only code that can write a request."""
    monkeypatch.setattr(ai_engine, "call_openai_gpt_mock",
                        _reply(f"Dạ vâng ạ. {BOOKING_TOKEN}"))

    reply, _ = process_chat_message(db, conv.id, "vay cho minh mot suat")

    assert BOOKING_TOKEN not in reply, "ký hiệu nội bộ không được lọt ra ngoài"
    db.refresh(conv)
    assert (conv.booking_state or {}).get("active") is True

    msg = db.query(Message).filter(Message.sender == "bot").order_by(Message.id.desc()).first()
    assert msg.evaluation_metadata.get("entered_via") == "model_token"


def test_the_prompt_forbids_claiming_a_booking(db, conv, monkeypatch):
    """The old rule told the model to "gửi booking request" — an action it has no
    way to perform, so it reported doing it instead."""
    captured = {}

    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(messages=None, **kw):
                    captured["system"] = messages[0]["content"]
                    class R:
                        choices = [type("C", (), {"message": type("M", (), {"content": "ok"})})]
                    return R()

    monkeypatch.setattr(ai_engine, "openai_client", FakeClient)
    process_chat_message(db, conv.id, "xin chao")

    system = captured["system"]
    assert "KHÔNG có khả năng ghi nhận" in system
    assert BOOKING_TOKEN in system
