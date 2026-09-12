"""A patient who says stop is not messaged again — but still gets their reminder.

Two mistakes are possible here and they fail in opposite directions.

Ignoring a refusal is the expensive one: the patient reports the Zalo OA for
spam, and an OA that collects spam reports early is very hard to recover. It is
also against Nghị định 13/2023 on personal data.

Over-reading one is quieter and just as bad. "Huy" is among the most common
Vietnamese given names and "hủy" almost always means cancel my appointment, so
treating either as a refusal silently cuts a real customer off from the clinic
for ever, and nobody finds out.

And a refusal is about marketing. Someone who said "stop selling to me" did not
say "stop telling me when to turn up" — withholding their appointment reminder
would be the opposite of respecting what they asked for.
"""
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core import clock
from backend.app.core.database import Base
from backend.app.models.models import (
    Branch, Clinic, Conversation, Doctor, PatientLead, Service,
)
from backend.app.services import patients

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
def clinic(db):
    c = Clinic(name="CareDesk", is_active=True)
    db.add(c)
    db.flush()
    db.add_all([Branch(clinic_id=c.id, name="CS1", address="1 Lê Lợi", is_active=True),
                Doctor(clinic_id=c.id, name="BS An", is_active=True)])
    db.commit()
    return c


@pytest.fixture
def patient(db, clinic):
    p = PatientLead(clinic_id=clinic.id, full_name="Chị Hoa", phone="0911222333")
    db.add(p)
    db.commit()
    return p


# --- what counts as a refusal -------------------------------------------------

@pytest.mark.parametrize("message", [
    "đừng nhắn nữa",
    "đừng nhắn tin nữa nhé",
    "ko muốn nhận tin",
    "không muốn nhận tin nhắn",
    "ngừng gửi tin cho tôi",
    "đừng liên hệ nữa",
    "STOP",
    "spam quá",
    "unsubscribe",
])
def test_a_refusal_is_recognised(message):
    assert patients.detects_opt_out(message) is True


@pytest.mark.parametrize("message", [
    "Huy",                      # one of the most common Vietnamese names
    "em là Huy",
    "hủy",                      # cancel the appointment, not the relationship
    "hủy lịch giúp em",
    "không rảnh hôm nay",
    "không biết nữa",
    "em cảm ơn",
    "cho em hỏi giá",
    "",
])
def test_an_ordinary_reply_is_not_mistaken_for_one(message):
    """The quiet failure. Each of these would cut a real customer off, and
    nobody would ever find out — so the list is deliberately narrow."""
    assert patients.detects_opt_out(message) is False


# --- what it stops, and what it does not --------------------------------------

def test_marketing_stops(db, patient):
    patients.opt_out(db, patient)
    db.commit()

    assert patients.may_send_marketing(patient) is False


def test_the_automation_choke_point_honours_it(db, clinic, patient):
    """Every follow-up, win-back and package nudge goes through one function.
    If the flag is not checked there, it is not checked anywhere."""
    from backend.app.services.events import deliver_to_patient

    db.add(Conversation(clinic_id=clinic.id, patient_id=patient.id, channel="web"))
    db.commit()
    assert deliver_to_patient(db, patient, "Ưu đãi tháng này...") is True

    patients.opt_out(db, patient)
    db.commit()

    assert deliver_to_patient(db, patient, "Ưu đãi tháng này...") is False


def test_appointment_reminders_are_not_marketing(db, patient):
    """They asked the clinic to stop selling, not to stop telling them when to
    turn up. Reminders do not route through the marketing gate at all."""
    import inspect

    from backend.app.services import reminder

    source = inspect.getsource(reminder)
    assert "may_send_marketing" not in source, (
        "nhắc lịch hẹn đang bị chặn bởi cờ từ chối tiếp thị — khách đặt lịch rồi "
        "sẽ không được nhắc giờ khám"
    )


def test_the_money_queue_does_not_offer_them(db, clinic, patient):
    """Leaving them on the list means a receptionist rings them, which is the
    one outcome the flag exists to prevent."""
    from backend.app.services import revenue_recovery as rr

    service = Service(clinic_id=clinic.id, name="Trị mụn", price=500_000,
                      duration_minutes=30, revisit_interval_days=30)
    db.add(service)
    db.flush()
    db.add(rr.RevenueOpportunity(
        clinic_id=clinic.id, patient_id=patient.id, opportunity_type=rr.LOST_BOOKING,
        dedupe_key="1", estimated_value=500_000, probability=0.3, status="open"))
    db.commit()
    assert len(rr.money_queue(db, clinic.id)) == 1

    patients.opt_out(db, patient)
    db.commit()

    assert rr.money_queue(db, clinic.id) == []


def test_opting_back_in_is_never_a_side_effect(db, patient):
    """Someone asking a question later has not withdrawn their refusal. Only an
    explicit request reverses it."""
    patients.opt_out(db, patient)
    db.commit()

    patients.upsert_lead(db, clinic_id=patient.clinic_id, phone=patient.phone,
                         full_name="Chị Hoa", source="zalo")
    db.commit()
    db.refresh(patient)

    assert patient.contact_opt_out is True

    patients.opt_in(db, patient)
    db.commit()
    assert patient.contact_opt_out is False


def test_the_refusal_is_acted_on_by_the_webhook_not_by_a_human_later(db):
    """"Đừng nhắn nữa" has to take effect on the message that says it. Waiting
    for someone to read the inbox means the next scheduled message goes out
    first, and proves the clinic was not listening."""
    import inspect

    from backend.app.api.endpoints import webhooks

    source = inspect.getsource(webhooks._handle_inbound_message)
    assert "detects_opt_out" in source
    assert "OPT_OUT_ACK" in source, "phải xác nhận lại — im lặng cũng là phớt lờ"
