"""When the AI is not sure, a human must actually be fetched.

The old rule required a reply to contain a handoff phrase **and** the literal
string "cần cấp cứu", so the only non-emergency handoff that could ever fire was
also an emergency. An ordinary "em không chắc, để lễ tân liên hệ lại bạn nhé"
set no status, notified nobody, and left the patient waiting for someone who was
never told.
"""
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models.models import (
    Branch, Clinic, Conversation, Doctor, Message, PatientLead, WorkingSchedule,
)
from backend.app.services import ai_engine
from backend.app.services.ai_engine import (
    HANDOFF_TOKEN, LLM_FAILURE_HANDOFF_THRESHOLD, is_within_working_hours,
    llm_failure_streak, process_chat_message,
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
    ai_engine._llm_failure_streak.clear()


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    """Never let the suite reach OpenAI: it is slow, costs money, and makes the
    assertions depend on whatever the model felt like saying."""
    monkeypatch.setattr(ai_engine, "openai_client", None)


@pytest.fixture
def conv(db):
    clinic = Clinic(name="CareDesk", is_active=True)
    db.add(clinic)
    db.flush()
    branch = Branch(clinic_id=clinic.id, name="CS1", address="1 A", is_active=True)
    patient = PatientLead(clinic_id=clinic.id, full_name="Khach", consent_given=True)
    db.add_all([branch, patient])
    db.flush()
    c = Conversation(clinic_id=clinic.id, patient_id=patient.id, channel="web",
                     status="bot_active")
    db.add(c)
    db.commit()
    c.branch = branch  # kept on the fixture for the schedule tests
    return c


def _mock_reply(text):
    """Replace the mock responder so we control exactly what the 'AI' says."""
    return lambda db, clinic, msg, locale="vi": text


# --- the regression ----------------------------------------------------------

def test_the_model_asking_for_a_human_actually_triggers_one(db, conv, monkeypatch):
    monkeypatch.setattr(ai_engine, "call_openai_gpt_mock",
                        _mock_reply(f"Dạ em chưa rõ ạ. {HANDOFF_TOKEN}"))

    reply, is_handoff = process_chat_message(db, conv.id, "bác sĩ nào mổ giỏi nhất?")

    assert is_handoff is True
    db.refresh(conv)
    assert conv.status == "handoff_requested"


def test_the_token_is_never_shown_to_the_patient(db, conv, monkeypatch):
    monkeypatch.setattr(ai_engine, "call_openai_gpt_mock",
                        _mock_reply(f"Dạ em chưa rõ ạ. {HANDOFF_TOKEN}"))
    reply, _ = process_chat_message(db, conv.id, "x")
    assert HANDOFF_TOKEN not in reply


def test_plain_uncertainty_without_the_token_still_hands_off(db, conv, monkeypatch):
    """Backstop for a model that ignores the instruction. This is the exact
    sentence that used to fall through the old `and "cần cấp cứu"` condition."""
    monkeypatch.setattr(ai_engine, "call_openai_gpt_mock",
                        _mock_reply("Em không chắc, để lễ tân sẽ liên hệ lại bạn nhé."))

    _, is_handoff = process_chat_message(db, conv.id, "x")
    assert is_handoff is True


def test_a_confident_answer_does_not_hand_off(db, conv, monkeypatch):
    monkeypatch.setattr(ai_engine, "call_openai_gpt_mock",
                        _mock_reply("Dạ dịch vụ trị mụn bên em giá 500.000đ ạ."))

    _, is_handoff = process_chat_message(db, conv.id, "trị mụn bao nhiêu?")
    assert is_handoff is False
    db.refresh(conv)
    assert conv.status == "bot_active"


# --- the LLM outage nobody could see ----------------------------------------

def test_repeated_llm_failures_escalate_to_a_human(db, conv, monkeypatch):
    """The mock answers from the clinic's real catalogue, so it never looks
    broken. Without this the clinic serves a keyword bot for an entire outage
    and finds out from a complaint."""
    class Boom:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    raise RuntimeError("OpenAI 503")

    monkeypatch.setattr(ai_engine, "openai_client", Boom)
    monkeypatch.setattr(ai_engine, "call_openai_gpt_mock", _mock_reply("Giá 500.000đ ạ."))

    for i in range(1, LLM_FAILURE_HANDOFF_THRESHOLD):
        _, is_handoff = process_chat_message(db, conv.id, "gia bao nhieu?")
        assert is_handoff is False, f"lần {i} chưa cần chuyển người thật"

    _, is_handoff = process_chat_message(db, conv.id, "gia bao nhieu?")
    assert is_handoff is True
    assert llm_failure_streak(conv.clinic_id) >= LLM_FAILURE_HANDOFF_THRESHOLD


def test_the_failure_streak_resets_after_a_good_answer(db, conv, monkeypatch):
    ai_engine._note_llm_failure(conv.clinic_id)
    ai_engine._note_llm_failure(conv.clinic_id)
    assert llm_failure_streak(conv.clinic_id) == 2

    ai_engine._note_llm_success(conv.clinic_id)
    assert llm_failure_streak(conv.clinic_id) == 0


def test_the_fallback_is_recorded_on_the_message(db, conv, monkeypatch):
    """So the dashboard can show 'AI đang suy giảm' instead of nothing."""
    monkeypatch.setattr(ai_engine, "call_openai_gpt_mock", _mock_reply("Giá 500.000đ ạ."))
    process_chat_message(db, conv.id, "x")

    msg = db.query(Message).filter(Message.sender == "bot").order_by(Message.id.desc()).first()
    assert msg.evaluation_metadata.get("fallback_mock") is True


# --- do not promise what the clinic cannot deliver --------------------------

def test_outside_working_hours_the_patient_is_told_when_to_expect_a_reply(db, conv, monkeypatch):
    doctor = Doctor(clinic_id=conv.clinic_id, name="BS A", is_active=True)
    db.add(doctor)
    db.flush()
    # Open only on the day before today's weekday -> definitely closed now.
    db.add(WorkingSchedule(doctor_id=doctor.id, branch_id=conv.branch.id,
                           day_of_week=(datetime.date.today().weekday() + 1) % 7,
                           start_time=datetime.time(8, 0), end_time=datetime.time(17, 0)))
    db.commit()

    monkeypatch.setattr(ai_engine, "call_openai_gpt_mock",
                        _mock_reply(f"Em chưa rõ ạ. {HANDOFF_TOKEN}"))
    reply, _ = process_chat_message(db, conv.id, "x")

    assert "ngoài giờ làm việc" in reply.lower()
    assert is_within_working_hours(db, conv.clinic_id) is False


def test_a_clinic_with_no_schedule_is_treated_as_open(db, conv):
    """A half-configured clinic must not tell every patient it is closed."""
    assert is_within_working_hours(db, conv.clinic_id) is True


def test_within_working_hours_promises_an_immediate_reply(db, conv, monkeypatch):
    doctor = Doctor(clinic_id=conv.clinic_id, name="BS A", is_active=True)
    db.add(doctor)
    db.flush()
    db.add(WorkingSchedule(doctor_id=doctor.id, branch_id=conv.branch.id,
                           day_of_week=datetime.date.today().weekday(),
                           start_time=datetime.time(0, 0), end_time=datetime.time(23, 59)))
    db.commit()

    monkeypatch.setattr(ai_engine, "call_openai_gpt_mock",
                        _mock_reply(f"Em chưa rõ ạ. {HANDOFF_TOKEN}"))
    reply, _ = process_chat_message(db, conv.id, "x")

    assert "ngoài giờ" not in reply.lower()
    assert "lễ tân" in reply.lower()
