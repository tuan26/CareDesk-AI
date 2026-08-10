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

    branch = Branch(clinic_id=clinic.id, name="CS1", address="1 A", is_active=True)
    service = Service(clinic_id=clinic.id, name="Tri mun", price=500000, duration_minutes=30)
    doctor = Doctor(clinic_id=clinic.id, name="BS A", is_active=True)
    patient = PatientLead(clinic_id=clinic.id, full_name="Khach", phone="0900000000",
                          consent_given=True)
    db.add_all([branch, service, doctor, patient])
    db.flush()
    starts = datetime.datetime.now() + datetime.timedelta(hours=1)
    db.add(Appointment(
        clinic_id=clinic.id, branch_id=branch.id, service_id=service.id,
        doctor_id=doctor.id, patient_id=patient.id, status="confirmed",
        start_time=starts, end_time=starts + datetime.timedelta(minutes=30),
    ))
    db.commit()

    monkeypatch.setattr(reminder, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)

    sent = await reminder.check_and_send_reminders()

    assert sent == 0, "nothing was delivered, so nothing may be counted as sent"
    assert db.query(ReminderLog).count() == 0, (
        "a ReminderLog here would permanently retire this reminder"
    )


def test_outbound_status_says_a_bare_install_cannot_reach_a_phone(db, clinic):
    status = outbound_status(db, clinic.id)
    assert status["can_reach_phone"] is False
    assert status["zns"] is False and status["sms"] is False


def test_delivery_is_falsy_when_undelivered_and_truthy_when_sent():
    assert not Delivery(CHANNEL_NONE, False)
    assert Delivery("zns", True)
