import datetime as dt
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.app.core.database import Base
from backend.app.models.models import (
    Clinic, Branch, Service, Doctor, WorkingSchedule, PatientLead, Conversation,
        DomainEvent, AutomationRule, ScheduledAction, RevenueRecord, ServicePackage,
    PatientPackage, Appointment, ReviewRequest, WaitlistEntry, BookingRequest
)

from backend.app.services.events import (
    emit_event, process_new_events, dispatch_due_actions, seed_default_automations
)
from backend.app.services.ai_engine import process_chat_message

engine = create_engine("sqlite:///:memory:")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    clinic = Clinic(name="PK Revenue", plan="pro", ai_quota_monthly=1000, monthly_fee=1500000)
    db.add(clinic)
    db.commit()
    seed_default_automations(db, clinic.id)

    branch = Branch(clinic_id=clinic.id, name="CN 1", address="1 Test")
    db.add(branch)
    service = Service(clinic_id=clinic.id, name="Điều trị mụn Chuẩn Y Khoa", price=450000, duration_minutes=60)
    db.add(service)
    db.commit()

    doctor = Doctor(clinic_id=clinic.id, name="BS Rev", branch_id=branch.id, is_active=True)
    db.add(doctor)
    db.commit()
    for day in range(7):
        db.add(WorkingSchedule(doctor_id=doctor.id, branch_id=branch.id, day_of_week=day,
                               start_time=dt.time(8, 0), end_time=dt.time(18, 0)))
    lead = PatientLead(clinic_id=clinic.id, full_name="Khách Doanh Thu", phone="0905556666", consent_given=True)
    db.add(lead)
    db.commit()
    conv = Conversation(clinic_id=clinic.id, patient_id=lead.id, channel="web", status="bot_active")
    db.add(conv)
    db.commit()

    yield db, clinic, lead, conv, service, doctor, branch

    db.close()
    Base.metadata.drop_all(bind=engine)


def test_price_asked_schedules_followup_and_booking_cancels_it(db_session):
    db, clinic, lead, conv, service, doctor, branch = db_session

    # Patient asks a price -> price_asked event -> follow-up scheduled (2d + 5d)
    process_chat_message(db, conv.id, "Trị mụn giá bao nhiêu vậy?")
    process_new_events(db)
    followups = db.query(ScheduledAction).filter(ScheduledAction.status == "pending").all()
    assert len(followups) >= 2  # 2-day and 5-day follow-ups

        # Patient sends a booking request -> it cancels pending follow-ups, before staff creates an appointment.
    process_chat_message(db, conv.id, "Tôi muốn đặt lịch trị mụn")
    process_chat_message(db, conv.id, "ngày mai")
    process_chat_message(db, conv.id, "1")
    assert db.query(Appointment).count() == 0
    assert db.query(BookingRequest).count() == 1

    process_new_events(db)


    cancelled = db.query(ScheduledAction).filter(ScheduledAction.status == "cancelled").count()
    assert cancelled >= 2


def test_completed_appointment_creates_revenue_and_review(db_session):
    db, clinic, lead, conv, service, doctor, branch = db_session
    from backend.app.api.endpoints.appointment import handle_status_transition

    appt = Appointment(clinic_id=clinic.id, patient_id=lead.id, service_id=service.id,
                       doctor_id=doctor.id, branch_id=branch.id,
                       start_time=dt.datetime.now(), end_time=dt.datetime.now(),
                       status="confirmed", booking_source="ai_chat")
    db.add(appt)
    db.commit()

    appt.status = "completed"
    handle_status_transition(db, appt, "confirmed")
    db.commit()

    # Revenue attributed to AI
    rec = db.query(RevenueRecord).first()
    assert rec is not None and rec.amount == 450000 and rec.source == "ai_chat"

    # appointment_completed event -> recall + review actions scheduled
    process_new_events(db)
    actions = db.query(ScheduledAction).filter(ScheduledAction.status == "pending").all()
    assert len(actions) >= 2  # recall (30d) + review ask (2h)

    # Force the review ask due now -> ReviewRequest created
    for a in actions:
        a.due_at = dt.datetime.now() - dt.timedelta(minutes=1)
    db.commit()
    dispatch_due_actions(db)
    assert db.query(ReviewRequest).filter(ReviewRequest.status == "pending").count() == 1

    # Patient replies "5" -> answered + referral code issued
    reply, handoff = process_chat_message(db, conv.id, "5")
    assert handoff is False and "Cảm ơn" in reply
    db.refresh(lead)
    assert lead.referral_code and lead.referral_code.startswith("CD")
    assert db.query(ReviewRequest).first().rating == 5

def test_low_rating_escalates(db_session):
    db, clinic, lead, conv, service, doctor, branch = db_session
    db.add(ReviewRequest(clinic_id=clinic.id, patient_id=lead.id))
    db.commit()

    reply, _ = process_chat_message(db, conv.id, "2")
    assert "xin lỗi" in reply.lower()
    review = db.query(ReviewRequest).first()
    assert review.status == "escalated" and review.rating == 2
    db.refresh(conv)
    assert conv.status == "handoff_requested"


def test_package_session_burn_and_used_up_event(db_session):
    db, clinic, lead, conv, service, doctor, branch = db_session
    from backend.app.api.endpoints.appointment import handle_status_transition

    pkg = ServicePackage(clinic_id=clinic.id, service_id=service.id, name="Gói mụn 2 buổi",
                         total_sessions=2, price=800000, validity_days=90)
    db.add(pkg)
    db.commit()
    pp = PatientPackage(clinic_id=clinic.id, patient_id=lead.id, package_id=pkg.id,
                        sessions_total=2, amount_paid=800000,
                        expires_at=dt.datetime.now() + dt.timedelta(days=90))
    db.add(pp)
    db.commit()

    for i in range(2):
        appt = Appointment(clinic_id=clinic.id, patient_id=lead.id, service_id=service.id,
                           doctor_id=doctor.id, branch_id=branch.id,
                           start_time=dt.datetime.now(), end_time=dt.datetime.now(),
                           status="confirmed", booking_source="staff")
        db.add(appt)
        db.commit()
        appt.status = "completed"
        handle_status_transition(db, appt, "confirmed")
        db.commit()

    db.refresh(pp)
    assert pp.sessions_used == 2 and pp.status == "used_up"
    # Package visits must not double-book revenue (package was prepaid)
    assert db.query(RevenueRecord).count() == 0
    assert db.query(DomainEvent).filter(DomainEvent.event_type == "package_used_up").count() == 1


def test_cancellation_notifies_waitlist(db_session):
    db, clinic, lead, conv, service, doctor, branch = db_session
    from backend.app.api.endpoints.appointment import handle_status_transition

    waiter = PatientLead(clinic_id=clinic.id, full_name="Khách Chờ", phone="0907778888", consent_given=True)
    db.add(waiter)
    db.commit()
    db.add(WaitlistEntry(clinic_id=clinic.id, patient_id=waiter.id, service_id=service.id))
    db.commit()

    appt = Appointment(clinic_id=clinic.id, patient_id=lead.id, service_id=service.id,
                       doctor_id=doctor.id, branch_id=branch.id,
                       start_time=dt.datetime.now() + dt.timedelta(days=1),
                       end_time=dt.datetime.now() + dt.timedelta(days=1, hours=1),
                       status="confirmed")
    db.add(appt)
    db.commit()

    appt.status = "cancelled"
    handle_status_transition(db, appt, "confirmed")
    db.commit()

    process_new_events(db)
    dispatch_due_actions(db)

    entry = db.query(WaitlistEntry).first()
    assert entry.status == "notified"
