"""A message that was not sent must never be recorded as sent.

This is not a cosmetic concern. ReminderLog is what the scheduler reads back to
decide "this appointment has already been reminded", so logging an undelivered
send retires the reminder permanently: the patient hears nothing, and wiring up
a real channel later does not rescue the appointments already marked. It also
makes every delivery number in the pilot report a lie.
"""
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models.models import (
    Appointment, Branch, ChannelIntegration, Clinic, Doctor, PatientLead,
    ReminderLog, Service,
)
from backend.app.services import channel_gateway
from backend.app.services.channel_gateway import (
    CHANNEL_NONE, Delivery, outbound_status, send_zns_or_sms, sms_is_configured,
    zns_is_configured,
)


def _make_appointment(db, clinic):
    """One confirmed appointment 20 hours out.

    Deliberately inside the 24h reminder window but outside the 2h one: an
    appointment that falls in both produces two independent outbox rows, and
    these tests are about how a single row behaves.
    """
    branch = Branch(clinic_id=clinic.id, name="CS1", address="1 A", is_active=True)
    service = Service(clinic_id=clinic.id, name="Tri mun", price=500000, duration_minutes=30)
    doctor = Doctor(clinic_id=clinic.id, name="BS A", is_active=True)
    patient = PatientLead(clinic_id=clinic.id, full_name="Khach", phone="0900000000",
                          consent_given=True)
    db.add_all([branch, service, doctor, patient])
    db.flush()
    starts = datetime.datetime.now() + datetime.timedelta(hours=20)
    appt = Appointment(
        clinic_id=clinic.id, branch_id=branch.id, service_id=service.id,
        doctor_id=doctor.id, patient_id=patient.id, status="confirmed",
        start_time=starts, end_time=starts + datetime.timedelta(minutes=30),
    )
    db.add(appt)
    db.commit()
    return appt

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
    db.commit()
    return c


@pytest.fixture(autouse=True)
def no_sms_by_default(monkeypatch):
    """Tests opt in to a configured provider; the default is a bare install."""
    monkeypatch.setattr(channel_gateway.settings, "SMS_PROVIDER", "", raising=False)
    monkeypatch.setattr(channel_gateway.settings, "SMS_API_KEY", "", raising=False)


# --- the core guarantee ------------------------------------------------------

def test_no_channel_configured_reports_failure_not_a_fake_sms(db, clinic):
    """Regression: this used to return the literal string "sms" — identical to a
    real send — after only printing to the console."""
    result = send_zns_or_sms(db, clinic.id, "0900000000", "nhac lich")

    assert result.delivered is False
    assert result.channel == CHANNEL_NONE
    assert result.channel != "sms"
    assert not result  # __bool__ follows `delivered`


def test_zalo_without_an_approved_template_is_not_usable(db, clinic):
    """An authorised OA is not enough: ZNS refuses to send without a template id
    approved by Zalo, which is the usual reason reminders quietly stop."""
    db.add(ChannelIntegration(clinic_id=clinic.id, channel="zalo", enabled=True,
                              access_token="tok", extra_config={}))
    db.commit()

    assert zns_is_configured(db, clinic.id) is False
    assert send_zns_or_sms(db, clinic.id, "0900000000", "x").delivered is False


def test_zalo_with_an_approved_template_counts_as_configured(db, clinic):
    db.add(ChannelIntegration(clinic_id=clinic.id, channel="zalo", enabled=True,
                              access_token="tok",
                              extra_config={"zns_template_id": "123"}))
    db.commit()
    assert zns_is_configured(db, clinic.id) is True


def test_a_disabled_integration_does_not_count(db, clinic):
    db.add(ChannelIntegration(clinic_id=clinic.id, channel="zalo", enabled=False,
                              access_token="tok",
                              extra_config={"zns_template_id": "123"}))
    db.commit()
    assert zns_is_configured(db, clinic.id) is False


def test_sms_needs_both_a_provider_and_a_key(monkeypatch):
    monkeypatch.setattr(channel_gateway.settings, "SMS_PROVIDER", "esms", raising=False)
    monkeypatch.setattr(channel_gateway.settings, "SMS_API_KEY", "", raising=False)
    assert sms_is_configured() is False

    monkeypatch.setattr(channel_gateway.settings, "SMS_API_KEY", "k", raising=False)
    assert sms_is_configured() is True

    # An unknown provider name must not be treated as usable.
    monkeypatch.setattr(channel_gateway.settings, "SMS_PROVIDER", "carrier-pigeon", raising=False)
    assert sms_is_configured() is False


def test_sms_falls_back_when_the_provider_rejects_the_message(db, clinic, monkeypatch):
    monkeypatch.setattr(channel_gateway.settings, "SMS_PROVIDER", "esms", raising=False)
    monkeypatch.setattr(channel_gateway.settings, "SMS_API_KEY", "k", raising=False)
    monkeypatch.setitem(channel_gateway._SMS_PROVIDERS, "esms", lambda p, t: False)

    result = send_zns_or_sms(db, clinic.id, "0900000000", "x")
    assert result.delivered is False
    assert result.channel == CHANNEL_NONE


def test_a_provider_exception_is_a_failure_not_a_crash(db, clinic, monkeypatch):
    def boom(phone, text):
        raise RuntimeError("nhà mạng từ chối")

    monkeypatch.setattr(channel_gateway.settings, "SMS_PROVIDER", "esms", raising=False)
    monkeypatch.setattr(channel_gateway.settings, "SMS_API_KEY", "k", raising=False)
    monkeypatch.setitem(channel_gateway._SMS_PROVIDERS, "esms", boom)

    result = send_zns_or_sms(db, clinic.id, "0900000000", "x")
    assert result.delivered is False
    assert "nhà mạng từ chối" in result.detail


def test_successful_sms_is_reported_as_sms(db, clinic, monkeypatch):
    monkeypatch.setattr(channel_gateway.settings, "SMS_PROVIDER", "esms", raising=False)
    monkeypatch.setattr(channel_gateway.settings, "SMS_API_KEY", "k", raising=False)
    monkeypatch.setitem(channel_gateway._SMS_PROVIDERS, "esms", lambda p, t: True)

    result = send_zns_or_sms(db, clinic.id, "0900000000", "x")
    assert result.delivered is True
    assert result.channel == "sms"


# --- the consequence the guarantee protects ----------------------------------

@pytest.mark.asyncio
async def test_scheduler_writes_no_reminder_log_when_nothing_was_delivered(db, clinic, monkeypatch):
    """The appointment must stay un-reminded so it is retried once a channel
    exists, instead of being marked done forever."""
    from backend.app.services import reminder

    _make_appointment(db, clinic)

    monkeypatch.setattr(reminder, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)

    sent = await reminder.check_and_send_reminders()

    assert sent == 0, "nothing was delivered, so nothing may be counted as sent"

    # The outbox records the attempt — "we tried and could not" must be visible,
    # not indistinguishable from "we never got round to it". What it must NOT do
    # is mark the reminder as handled.
    entry = db.query(ReminderLog).filter(ReminderLog.medium == "phone").one()
    assert entry.status == "failed"
    assert entry.channel == CHANNEL_NONE
    assert "chưa cấu hình" in entry.last_error
    assert entry.attempts == 0, (
        "no provider was contacted, so this must not consume a retry — otherwise "
        "reminders queued up while waiting for a Zalo OA are retired before it arrives"
    )


@pytest.mark.asyncio
async def test_an_unconfigured_channel_never_exhausts_its_retries(db, clinic, monkeypatch):
    """The clinic waits three weeks for ZNS approval. Every reminder that piled
    up in the meantime must still go out on the day it is switched on."""
    from backend.app.services import reminder

    _make_appointment(db, clinic)
    monkeypatch.setattr(reminder, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)

    for _ in range(reminder.MAX_SEND_ATTEMPTS + 2):
        await reminder.check_and_send_reminders()

    entry = db.query(ReminderLog).filter(ReminderLog.medium == "phone").one()
    assert entry.attempts == 0
    assert reminder._open_outbox_entry(db, entry.appointment_id, "24h", "phone") is not None

    # Credentials land -> the very next tick delivers it.
    monkeypatch.setattr(channel_gateway.settings, "SMS_PROVIDER", "esms", raising=False)
    monkeypatch.setattr(channel_gateway.settings, "SMS_API_KEY", "k", raising=False)
    monkeypatch.setitem(channel_gateway._SMS_PROVIDERS, "esms", lambda p, t: True)

    assert await reminder.check_and_send_reminders() == 1
    db.refresh(entry)
    assert entry.status == "sent" and entry.channel == "sms"


@pytest.mark.asyncio
async def test_a_provider_rejection_stops_retrying(db, clinic, monkeypatch):
    """A bad number is refused identically every time. Retrying it on every tick
    for 24 hours costs money once a real gateway is billing per attempt."""
    from backend.app.services import reminder

    _make_appointment(db, clinic)
    monkeypatch.setattr(reminder, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(channel_gateway.settings, "SMS_PROVIDER", "esms", raising=False)
    monkeypatch.setattr(channel_gateway.settings, "SMS_API_KEY", "k", raising=False)

    calls = []
    monkeypatch.setitem(channel_gateway._SMS_PROVIDERS, "esms",
                        lambda p, t: calls.append(1) and False)

    for _ in range(4):
        await reminder.check_and_send_reminders()

    assert len(calls) == 1, "một lần từ chối là đủ, không thử lại"
    entry = db.query(ReminderLog).filter(ReminderLog.medium == "phone").one()
    assert entry.status == "failed"
    assert entry.attempts >= reminder.MAX_SEND_ATTEMPTS


@pytest.mark.asyncio
async def test_a_transport_error_is_retried_up_to_the_ceiling(db, clinic, monkeypatch):
    from backend.app.services import reminder

    _make_appointment(db, clinic)
    monkeypatch.setattr(reminder, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(channel_gateway.settings, "SMS_PROVIDER", "esms", raising=False)
    monkeypatch.setattr(channel_gateway.settings, "SMS_API_KEY", "k", raising=False)

    calls = []

    def timeout(phone, text):
        calls.append(1)
        raise TimeoutError("nhà mạng không phản hồi")

    monkeypatch.setitem(channel_gateway._SMS_PROVIDERS, "esms", timeout)

    for _ in range(reminder.MAX_SEND_ATTEMPTS):
        await reminder.check_and_send_reminders()
    at_ceiling = len(calls)
    assert at_ceiling == reminder.MAX_SEND_ATTEMPTS, "mỗi lượt thử đúng một lần"

    for _ in range(5):
        await reminder.check_and_send_reminders()
    assert len(calls) == at_ceiling, "chạm trần rồi thì không gọi nhà mạng nữa"


# --- sandbox and mock: run the flow without touching a real handset ----------

def test_the_mock_provider_completes_the_flow_but_reaches_nobody(db, clinic, monkeypatch):
    monkeypatch.setattr(channel_gateway.settings, "SMS_PROVIDER", "mock", raising=False)

    result = send_zns_or_sms(db, clinic.id, "0900000000", "x")
    assert result.delivered is True, "luồng chạy xong, scheduler không cần thử lại"
    assert result.reached_patient is False, "không ai nhận được tin này"
    assert sms_is_configured() is True
    assert channel_gateway.sms_reaches_real_phones() is False


def test_esms_sandbox_sends_the_sandbox_flag(db, clinic, monkeypatch):
    """The value of sandbox over the mock is that it exercises real credentials
    and real error handling, so the request must actually go out - with the flag."""
    monkeypatch.setattr(channel_gateway.settings, "SMS_PROVIDER", "esms", raising=False)
    monkeypatch.setattr(channel_gateway.settings, "SMS_API_KEY", "k", raising=False)
    monkeypatch.setattr(channel_gateway.settings, "SMS_SANDBOX", True, raising=False)

    captured = {}

    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"CodeResult": "100"}

    def fake_post(url, json=None, **kw):
        captured.update(json or {})
        return Resp()

    monkeypatch.setattr(channel_gateway.httpx, "post", fake_post)

    result = send_zns_or_sms(db, clinic.id, "0900000000", "nhac lich")
    assert captured.get("Sandbox") == "1"
    assert result.delivered is True
    assert result.reached_patient is False
    assert result.channel == "sms_sandbox", "phải phân biệt được với SMS thật"


def test_a_simulated_sender_does_not_make_the_clinic_look_ready(db, clinic, monkeypatch):
    """Green light on the dashboard while every message is swallowed by a
    sandbox is exactly the false confidence this module exists to prevent."""
    monkeypatch.setattr(channel_gateway.settings, "SMS_PROVIDER", "mock", raising=False)

    status = outbound_status(db, clinic.id)
    assert status["can_reach_phone"] is False
    assert status["sms"] is False
    assert status["sms_simulated"] is True
    assert status["sms_mode"] == "mock"


def test_speedsms_has_no_sandbox_mode(monkeypatch):
    """Unverified, so not implemented: believing messages are suppressed while
    they are in fact sent and billed is worse than having no sandbox at all."""
    monkeypatch.setattr(channel_gateway.settings, "SMS_PROVIDER", "speedsms", raising=False)
    monkeypatch.setattr(channel_gateway.settings, "SMS_API_KEY", "k", raising=False)
    monkeypatch.setattr(channel_gateway.settings, "SMS_SANDBOX", True, raising=False)

    captured = {}

    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"status": "success"}

    monkeypatch.setattr(channel_gateway.httpx, "post",
                        lambda url, json=None, **kw: (captured.update(json or {}), Resp())[1])
    channel_gateway._send_speedsms("0900000000", "x")

    assert "Sandbox" not in captured and "sandbox" not in captured


def test_outbound_status_says_a_bare_install_cannot_reach_a_phone(db, clinic):
    status = outbound_status(db, clinic.id)
    assert status["can_reach_phone"] is False
    assert status["zns"] is False and status["sms"] is False


def test_delivery_is_falsy_when_undelivered_and_truthy_when_sent():
    assert not Delivery(CHANNEL_NONE, False)
    assert Delivery("zns", True)
