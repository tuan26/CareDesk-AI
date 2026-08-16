"""Coming back to a conversation, without handing it to a stranger.

Reopening the panel started from nothing every time: the consent form again, the
greeting again, an assistant with no idea what had just been discussed. Two
threads from the same person twenty minutes apart, in the inbox, as separate
conversations.

The obvious fix is to resume on the phone number, and it is the wrong one. A
phone number is not a secret — it is printed on receipts, forwarded in group
chats, written on parcels — so resuming on one would let anyone who knows a
number read that person's medical conversation. Continuity is keyed on the token
the browser holds instead: possession, not knowledge.

Which mattered more than it should have, because the endpoint that returns those
messages was reachable with no token at all.
"""
import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core import clock
from backend.app.core.config import settings
from backend.app.core.database import Base, get_db
from backend.app.main import app
from backend.app.models.models import Clinic, Conversation, Message, PatientLead
from backend.app.services.public_chat_session import issue_public_chat_session

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                       poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

API = "/api/v1/chat"


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


def _conversation(db, name="Chị Hoa", phone="0901234567"):
    clinic = db.query(Clinic).first()
    if clinic is None:
        clinic = Clinic(name="CareDesk", is_active=True)
        db.add(clinic)
        db.flush()
    patient = PatientLead(clinic_id=clinic.id, full_name=name, phone=phone)
    db.add(patient)
    db.flush()
    conv = Conversation(clinic_id=clinic.id, patient_id=patient.id, status="bot_active")
    db.add(conv)
    db.flush()
    db.add_all([
        Message(conversation_id=conv.id, sender="patient", content="trị mụn bao nhiêu tiền"),
        Message(conversation_id=conv.id, sender="bot", content="Dạ 450.000đ ạ"),
    ])
    conv.public_session_token = issue_public_chat_session(db, conv.id)
    db.commit()
    return conv


# --- the hole this closed -----------------------------------------------------

def test_chat_history_is_not_readable_without_the_token(client, db):
    """It was. PUBLIC_CHAT_REQUIRE_SESSION_TOKEN defaulted to false, so counting
    upwards through /chat/conversations/{id}/messages returned strangers'
    medical conversations to anyone who asked."""
    conv = _conversation(db)

    assert client.get(f"{API}/conversations/{conv.id}/messages").status_code == 403
    assert client.get(f"{API}/conversations/{conv.id}/resume").status_code == 403


def test_another_visitors_token_does_not_open_this_thread(client, db):
    mine = _conversation(db, name="Chị Hoa", phone="0901234567")
    theirs = _conversation(db, name="Anh Nam", phone="0900000000")

    response = client.get(f"{API}/conversations/{theirs.id}/resume",
                          headers={"X-CareDesk-Session": mine.public_session_token})

    assert response.status_code == 403


def test_knowing_the_phone_number_is_not_enough(client, db):
    """The whole reason continuity is keyed on the browser: a phone number is
    printed on receipts and shared in group chats."""
    conv = _conversation(db, phone="0912345678")

    started = client.post(f"{API}/conversations", json={
        "full_name": "Người khác", "phone": "0912345678", "source": "web",
        "consent_given": True, "clinic_id": conv.clinic_id, "locale": "vi"})

    assert started.status_code == 200
    # Same patient record, but a conversation of their own — not the earlier one.
    assert started.json()["id"] != conv.id
    resumed = client.get(f"{API}/conversations/{started.json()['id']}/resume",
                         headers={"X-CareDesk-Session": started.json()["public_session_token"]})
    # A greeting of its own, and nothing the previous visitor said.
    contents = [m["content"] for m in resumed.json()["messages"]]
    assert "trị mụn bao nhiêu tiền" not in contents
    assert all(m["sender"] == "bot" for m in resumed.json()["messages"])


# --- and the continuity it enables -------------------------------------------

def test_the_browser_that_had_the_conversation_gets_it_back(client, db):
    conv = _conversation(db)

    response = client.get(f"{API}/conversations/{conv.id}/resume",
                          headers={"X-CareDesk-Session": conv.public_session_token})

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == conv.id
    assert [m["content"] for m in body["messages"]] == [
        "trị mụn bao nhiêu tiền", "Dạ 450.000đ ạ"]


def test_reading_does_not_rotate_the_token(client, db):
    """Rotating on reads as well as writes is what stranded the browser.

    The four-second poll and a slow send could each rotate while both were in
    flight; the browser kept whichever reply landed last, the database held the
    other, and only one previous token is remembered. Every request after that
    was 403 — and because the send path ignored the status, the panel showed no
    answer and no error at all.
    """
    conv = _conversation(db)
    original = conv.public_session_token

    first = client.get(f"{API}/conversations/{conv.id}/resume",
                       headers={"X-CareDesk-Session": original})
    second = client.get(f"{API}/conversations/{conv.id}/messages",
                        headers={"X-CareDesk-Session": original})

    assert first.status_code == 200 and second.status_code == 200
    assert first.headers.get("X-CareDesk-Session") == original


def test_sending_still_rotates(client, db):
    """Where rotation earns its keep: a write is user-initiated and serial."""
    conv = _conversation(db)

    response = client.post(f"{API}/conversations/{conv.id}/messages",
                           json={"content": "xin chào"},
                           headers={"X-CareDesk-Session": conv.public_session_token})

    rotated = response.headers.get("X-CareDesk-Session")
    assert rotated and rotated != conv.public_session_token


def test_a_poll_during_a_send_does_not_break_the_session(client, db):
    """The race, in the order it actually happened: poll, send, poll."""
    conv = _conversation(db)
    token = conv.public_session_token

    assert client.get(f"{API}/conversations/{conv.id}/messages",
                      headers={"X-CareDesk-Session": token}).status_code == 200
    sent = client.post(f"{API}/conversations/{conv.id}/messages",
                       json={"content": "trị mụn bao nhiêu"},
                       headers={"X-CareDesk-Session": token})
    assert sent.status_code == 200
    token = sent.headers.get("X-CareDesk-Session") or token

    # The poll that was already in flight used the pre-send token; the one after
    # uses what the send handed back. Both must still work.
    assert client.get(f"{API}/conversations/{conv.id}/messages",
                      headers={"X-CareDesk-Session": conv.public_session_token}).status_code == 200
    assert client.get(f"{API}/conversations/{conv.id}/messages",
                      headers={"X-CareDesk-Session": token}).status_code == 200


def test_a_stale_thread_is_not_resumed(client, db):
    """A fortnight-old exchange is clutter rather than context, and its
    half-finished booking points at dates that have passed."""
    conv = _conversation(db)
    conv.updated_at = clock.now() - datetime.timedelta(
        hours=settings.PUBLIC_CHAT_RESUME_MAX_AGE_HOURS + 1)
    db.commit()

    response = client.get(f"{API}/conversations/{conv.id}/resume",
                          headers={"X-CareDesk-Session": conv.public_session_token})

    assert response.status_code == 410


def test_a_booking_left_on_a_past_date_is_cleared(client, db):
    """Otherwise the patient comes back and is answered with "ngày bạn chọn đã
    qua mất rồi" for a day they never re-chose."""
    conv = _conversation(db)
    yesterday = (clock.today() - datetime.timedelta(days=1)).isoformat()
    conv.booking_state = {"active": True, "service_id": 1, "date": yesterday,
                          "proposed_slots": ["09:00"]}
    db.commit()

    client.get(f"{API}/conversations/{conv.id}/resume",
               headers={"X-CareDesk-Session": conv.public_session_token})
    db.refresh(conv)

    assert "date" not in conv.booking_state
    assert "proposed_slots" not in conv.booking_state
    # The rest of the intent survives: they still wanted that service.
    assert conv.booking_state["service_id"] == 1


def test_the_greeting_is_part_of_the_transcript(client, db):
    """Every client drew it locally and none stored it, so reception's inbox
    opened on the patient's first question — and resuming lost it."""
    clinic = Clinic(name="CareDesk", is_active=True)
    db.add(clinic)
    db.commit()

    started = client.post(f"{API}/conversations", json={
        "full_name": "Chị Mai", "phone": "0977000111", "source": "web",
        "consent_given": True, "clinic_id": clinic.id, "locale": "vi"}).json()

    stored = db.query(Message).filter(Message.conversation_id == started["id"]).all()
    assert len(stored) == 1
    assert stored[0].sender == "bot"
    assert "Chị Mai" in stored[0].content
