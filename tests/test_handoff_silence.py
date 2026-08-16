"""Waiting for a receptionist is not the same as having one.

Both were `handoff_requested`, so both silenced the assistant. A patient whose
question went to the queue at eight in the evening then sent two more messages —
"có những gói khám nào tôi có thể đặt được", "tư vấn thêm cho tôi các gói khám" —
and got nothing back at all. The service list answers the first one.

Silence is not neutral. It reads as broken, and a patient who thinks the clinic
is broken does not ring back in the morning. So the assistant keeps answering
while the queue is unattended — unless answering is the actual danger.
"""
import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core import handoff
from backend.app.core.database import Base, get_db
from backend.app.main import app
from backend.app.models.models import (
    Clinic, Conversation, Message, PatientLead, Service,
)
from backend.app.services.public_chat_session import issue_public_chat_session

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
def conv(db):
    clinic = Clinic(name="CareDesk", is_active=True)
    db.add(clinic)
    db.flush()
    db.add(Service(clinic_id=clinic.id, name="Trị mụn", price=450000, duration_minutes=45))
    patient = PatientLead(clinic_id=clinic.id, full_name="Chị Hoa", phone="0901234567")
    db.add(patient)
    db.flush()
    c = Conversation(clinic_id=clinic.id, patient_id=patient.id, status="bot_active")
    db.add(c)
    db.flush()
    # Public chat endpoints now always require the conversation-bound token —
    # they used to hand a stranger's history to anyone who guessed the id.
    c.public_session_token = issue_public_chat_session(db, c.id)
    db.commit()
    return c


def _send(client, conv, text):
    return client.post(f"/api/v1/chat/conversations/{conv.id}/messages",
                       json={"content": text},
                       headers={"X-CareDesk-Session": conv.public_session_token})


def _bot_replies(db, conv):
    return db.query(Message).filter(Message.conversation_id == conv.id,
                                    Message.sender == "bot").count()


# --- the rule, stated plainly -------------------------------------------------

def test_a_receptionist_in_the_room_silences_the_assistant():
    """Two answers to one question is worse than a slow one."""
    assert handoff.assistant_may_reply("agent_active", None) is False
    assert handoff.assistant_may_reply("agent_active", handoff.UNSURE) is False


def test_an_unattended_queue_does_not():
    """Nobody has picked up. Answering beats silence."""
    assert handoff.assistant_may_reply("handoff_requested", handoff.UNSURE) is True
    assert handoff.assistant_may_reply("handoff_requested", handoff.PHRASE) is True
    assert handoff.assistant_may_reply("handoff_requested", handoff.LLM_DOWN) is True


@pytest.mark.parametrize("reason", sorted(handoff.MUTING_REASONS))
def test_some_reasons_silence_it_regardless(reason):
    """A safety trigger is the one case where a plausible sentence is the harm.
    Quota and a review escalation are business decisions the assistant must not
    talk its way around."""
    assert handoff.assistant_may_reply("handoff_requested", reason) is False


def test_an_unknown_reason_errs_towards_answering():
    """Rows that predate the column carry no reason. The worst case is a patient
    in an abandoned conversation getting an answer."""
    assert handoff.assistant_may_reply("handoff_requested", None) is True


# --- end to end, through the endpoint the widget calls ------------------------

def test_a_question_asked_while_waiting_gets_an_answer(client, db, conv):
    """The reported bug: two messages into a queued conversation, no reply."""
    conv.status = "handoff_requested"
    conv.handoff_reason = handoff.UNSURE
    db.commit()

    before = _bot_replies(db, conv)
    assert _send(client, conv, "có những gói khám nào tôi có thể đặt được").status_code == 200

    assert _bot_replies(db, conv) > before, "khách nhắn khi đang chờ lễ tân mà không có hồi đáp"


def test_a_safety_handoff_stays_silent(client, db, conv):
    """The assistant must not resume a conversation that was escalated for a
    clinical reason, however ordinary the next message looks."""
    conv.status = "handoff_requested"
    conv.handoff_reason = handoff.SAFETY
    db.commit()

    before = _bot_replies(db, conv)
    assert _send(client, conv, "có những gói khám nào").status_code == 200

    assert _bot_replies(db, conv) == before


def test_a_message_to_a_live_agent_is_stored_not_answered(client, db, conv):
    conv.status = "agent_active"
    db.commit()

    before = _bot_replies(db, conv)
    _send(client, conv, "dạ em vẫn đây")

    assert _bot_replies(db, conv) == before
    assert db.query(Message).filter(Message.conversation_id == conv.id,
                                    Message.sender == "patient").count() == 1


def test_the_conversation_stays_flagged_for_staff(client, db, conv):
    """Answering a follow-up must not clear the queue: the question that needed
    a person still needs one."""
    conv.status = "handoff_requested"
    conv.handoff_reason = handoff.UNSURE
    db.commit()

    _send(client, conv, "phòng khám có những gói nào")
    db.refresh(conv)

    assert conv.status == "handoff_requested"
