"""The chain from a missed patient to money in the bank, and what may be claimed.

Detection answers "there are 22 opportunities". The owner's real question comes
next — *of those, how much did CareDesk actually bring back, and was it really
CareDesk?* — and every way of getting that wrong makes the number bigger, never
smaller. So this file is mostly about refusing credit:

  * one booking is one recovery, however many opportunities a patient carries
  * a booking is not money until someone has paid
  * a patient nobody contacted is the baseline, not a win
  * a booking months after the only message is not attributable to it

The first of those is here because it shipped broken. A patient overdue for a
revisit who had also left a booking request and once no-showed had three open
opportunities, and one ₫2.000.000 appointment closed all three as recovered —
₫6.000.000 on the dashboard for one visit.
"""
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core import clock
from backend.app.core.database import Base
from backend.app.models.models import (
    Appointment, BookingRequest, Branch, Clinic, Conversation, Doctor, Message,
    PatientLead, RevenueAction, RevenueOpportunity, RevenueRecord, Service,
)
from backend.app.services import revenue_recovery as rr

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
    c = Clinic(name="CareDesk", is_active=True, monthly_fee=2_000_000)
    db.add(c)
    db.flush()
    db.add_all([Branch(clinic_id=c.id, name="CS1", address="1 Lê Lợi", is_active=True),
                Doctor(clinic_id=c.id, name="BS An", is_active=True)])
    db.commit()
    return c


@pytest.fixture
def service(db, clinic):
    s = Service(clinic_id=clinic.id, name="Peel da", price=2_000_000,
                duration_minutes=45, revisit_interval_days=30)
    db.add(s)
    db.commit()
    return s


def _patient(db, clinic, name="Chị Hoa", phone="0901234567"):
    p = PatientLead(clinic_id=clinic.id, full_name=name, phone=phone)
    db.add(p)
    db.commit()
    return p


def _appointment(db, clinic, patient, service, days_from_now, status="confirmed"):
    branch = db.query(Branch).filter(Branch.clinic_id == clinic.id).first()
    doctor = db.query(Doctor).filter(Doctor.clinic_id == clinic.id).first()
    start = clock.now() + datetime.timedelta(days=days_from_now)
    appt = Appointment(clinic_id=clinic.id, patient_id=patient.id, service_id=service.id,
                       doctor_id=doctor.id, branch_id=branch.id, status=status,
                       start_time=start, end_time=start + datetime.timedelta(minutes=45))
    db.add(appt)
    db.commit()
    return appt


def _three_open_opportunities(db, clinic, patient, service):
    """Overdue for a revisit, a booking request nobody rang, and a no-show."""
    _appointment(db, clinic, patient, service, days_from_now=-60, status="completed")
    _appointment(db, clinic, patient, service, days_from_now=-30, status="no_show")
    db.add(BookingRequest(clinic_id=clinic.id, patient_id=patient.id, service_id=service.id,
                          service_or_need="Peel da", full_name=patient.full_name,
                          contact_value=patient.phone, status="requested",
                          created_at=clock.now() - datetime.timedelta(days=5)))
    db.commit()
    rr.run_detection(db, clinic.id)
    return db.query(RevenueOpportunity).all()


# --- one booking is one recovery ---------------------------------------------

def test_one_booking_credits_exactly_one_opportunity(db, clinic, service):
    """The ₫6.000.000 bug. Three opportunities, one visit, one recovery."""
    patient = _patient(db, clinic)
    assert len(_three_open_opportunities(db, clinic, patient, service)) == 3

    _appointment(db, clinic, patient, service, days_from_now=2)
    rr.run_detection(db, clinic.id)

    booked = db.query(RevenueOpportunity).filter(RevenueOpportunity.status == "booked").all()
    superseded = db.query(RevenueOpportunity).filter(
        RevenueOpportunity.status == "superseded").all()

    assert len(booked) == 1, "một lần đặt lịch chỉ được ghi công cho một cơ hội"
    assert len(superseded) == 2


def test_the_superseded_ones_never_carry_money(db, clinic, service):
    """They were real misses, so they are kept — but a visit that was paid for
    once must not appear as revenue three times."""
    patient = _patient(db, clinic)
    _three_open_opportunities(db, clinic, patient, service)
    appt = _appointment(db, clinic, patient, service, days_from_now=2)
    rr.run_detection(db, clinic.id)

    appt.status = "completed"
    db.add(RevenueRecord(clinic_id=clinic.id, patient_id=patient.id,
                         appointment_id=appt.id, amount=2_000_000))
    db.commit()
    rr.run_detection(db, clinic.id)

    total = sum(float(o.recovered_amount or 0) for o in db.query(RevenueOpportunity).all())
    assert total == 2_000_000, f"khách trả 2 triệu nhưng hệ thống ghi {total:,.0f}"


def test_superseded_opportunities_are_left_out_of_the_conversion_rate(db, clinic, service):
    """Counting them as won inflates the rate, counting them as lost deflates
    it. They are evidence of neither, so they are evidence of nothing."""
    patient = _patient(db, clinic)
    opportunities = _three_open_opportunities(db, clinic, patient, service)
    for o in opportunities:
        o.is_holdout = False
    db.commit()
    rr.record_action(db, opportunities[0], "sms")
    db.commit()

    _appointment(db, clinic, patient, service, days_from_now=2)
    rr.run_detection(db, clinic.id)

    performance = rr.recovery_performance(db, clinic.id)
    assert performance["contacted"] == 1, "chỉ một cơ hội được liên hệ"
    assert performance["recovered_count"] == 1


# --- a booking is not money ---------------------------------------------------

def test_a_booking_is_not_revenue_until_someone_pays(db, clinic, service):
    """The month a patient books is often not the month they turn up, and the
    estimate is what we hoped for. Putting it in the recovered column is how a
    dashboard ends up disagreeing with the bank."""
    patient = _patient(db, clinic)
    opportunities = _three_open_opportunities(db, clinic, patient, service)
    for o in opportunities:
        o.is_holdout = False
    rr.record_action(db, opportunities[0], "sms")
    db.commit()

    _appointment(db, clinic, patient, service, days_from_now=2)
    rr.run_detection(db, clinic.id)

    funnel = rr.recovery_funnel(db, clinic.id)
    assert funnel["booked"] == 1
    assert funnel["completed"] == 0
    assert funnel["revenue_recovered"] == 0, "chưa ai trả tiền mà đã ghi doanh thu"


def test_the_funnel_counts_only_people_the_clinic_actually_reached(db, clinic, service):
    """A patient who came back on their own does not belong in an outreach
    funnel. Letting them in would make the contact-to-booking rate look like
    the clinic's messages were working when nothing had been sent."""
    patient = _patient(db, clinic)
    _three_open_opportunities(db, clinic, patient, service)
    _appointment(db, clinic, patient, service, days_from_now=2)
    rr.run_detection(db, clinic.id)

    funnel = rr.recovery_funnel(db, clinic.id)

    assert funnel["contacted"] == 0
    assert funnel["booked"] == 0, "khách tự quay lại không được tính vào funnel liên hệ"


def test_the_amount_recorded_is_the_money_not_the_estimate(db, clinic, service):
    """The patient was quoted ₫2.000.000 and paid ₫1.200.000 after a discount.
    The lower number is the true one."""
    patient = _patient(db, clinic)
    _three_open_opportunities(db, clinic, patient, service)
    appt = _appointment(db, clinic, patient, service, days_from_now=2)
    rr.run_detection(db, clinic.id)

    appt.status = "completed"
    db.add(RevenueRecord(clinic_id=clinic.id, patient_id=patient.id,
                         appointment_id=appt.id, amount=1_200_000))
    db.commit()
    rr.run_detection(db, clinic.id)

    won = db.query(RevenueOpportunity).filter(RevenueOpportunity.status == "recovered").one()
    assert won.recovered_amount == 1_200_000
    assert won.resolved_revenue_record_id is not None, "phải truy được về phiếu thu"


def test_a_visit_paid_by_an_existing_package_recovers_no_new_money(db, clinic, service):
    """The visit happened and the opportunity is genuinely recovered — but the
    clinic was paid for it months ago and must not be shown it twice."""
    patient = _patient(db, clinic)
    _three_open_opportunities(db, clinic, patient, service)
    appt = _appointment(db, clinic, patient, service, days_from_now=2)
    rr.run_detection(db, clinic.id)

    appt.status = "completed"  # no RevenueRecord: the package covered it
    db.commit()
    rr.run_detection(db, clinic.id)

    won = db.query(RevenueOpportunity).filter(RevenueOpportunity.status == "recovered").one()
    assert won.recovered_amount == 0.0


def test_a_booking_that_no_shows_goes_to_lost_not_back_to_open(db, clinic, service):
    """Silently reopening it would put the patient back on tomorrow's queue with
    no memory that they already stood the clinic up."""
    patient = _patient(db, clinic)
    _three_open_opportunities(db, clinic, patient, service)
    appt = _appointment(db, clinic, patient, service, days_from_now=2)
    rr.run_detection(db, clinic.id)

    appt.status = "no_show"
    db.commit()
    rr.run_detection(db, clinic.id)

    opportunity = db.query(RevenueOpportunity).filter(
        RevenueOpportunity.resolved_appointment_id == appt.id,
        RevenueOpportunity.status != "superseded").one()
    assert opportunity.status == "lost"
    assert opportunity.loss_reason == "no_show"


# --- who gets the credit ------------------------------------------------------

def test_a_patient_nobody_contacted_is_organic_not_a_win(db, clinic, service):
    """The central refusal. They came back on their own; claiming that as
    recovered revenue is the lie this whole feature exists to avoid."""
    patient = _patient(db, clinic)
    _three_open_opportunities(db, clinic, patient, service)
    _appointment(db, clinic, patient, service, days_from_now=2)
    rr.run_detection(db, clinic.id)

    booked = db.query(RevenueOpportunity).filter(RevenueOpportunity.status == "booked").one()
    assert booked.attribution_class == rr.ORGANIC


def test_booking_soon_after_contact_is_direct(db, clinic, service):
    patient = _patient(db, clinic)
    opportunities = _three_open_opportunities(db, clinic, patient, service)
    rr.record_action(db, opportunities[0], "sms")
    db.commit()

    _appointment(db, clinic, patient, service, days_from_now=2)
    rr.run_detection(db, clinic.id)

    booked = db.query(RevenueOpportunity).filter(RevenueOpportunity.status == "booked").one()
    assert booked.attribution_class == rr.DIRECT


def test_booking_long_after_the_only_message_is_not_attributable(db, clinic, service):
    """Without a ceiling every patient who ever returns eventually credits some
    old opportunity, and recovered revenue grows on its own."""
    patient = _patient(db, clinic)
    opportunities = _three_open_opportunities(db, clinic, patient, service)
    target = opportunities[0]
    rr.record_action(db, target, "sms")
    target.contacted_at = clock.now() - datetime.timedelta(days=rr.ATTRIBUTION_WINDOW_DAYS + 20)
    db.commit()

    _appointment(db, clinic, patient, service, days_from_now=1)
    rr.run_detection(db, clinic.id)

    booked = db.query(RevenueOpportunity).filter(RevenueOpportunity.status == "booked").one()
    assert booked.attribution_class == rr.UNKNOWN


def test_only_direct_and_assisted_may_be_claimed(db, clinic, service):
    """Organic revenue is reported so the total reconciles, never so it can be
    added into what the product takes credit for."""
    patient = _patient(db, clinic)
    _three_open_opportunities(db, clinic, patient, service)
    appt = _appointment(db, clinic, patient, service, days_from_now=2)
    rr.run_detection(db, clinic.id)
    appt.status = "completed"
    db.add(RevenueRecord(clinic_id=clinic.id, patient_id=patient.id,
                         appointment_id=appt.id, amount=2_000_000))
    db.commit()
    rr.run_detection(db, clinic.id)

    attribution = rr.attribution_summary(db, clinic.id)
    assert attribution["organic_revenue"] == 2_000_000
    assert attribution["attributable_revenue"] == 0, \
        "khách tự quay lại không được tính vào doanh thu CareDesk mang về"


# --- the outreach log ---------------------------------------------------------

def test_a_later_nudge_does_not_restart_the_attribution_clock(db, clinic, service):
    """Otherwise a lead contacted in January and nudged in March looks freshly
    won in March, and every stale opportunity can be made to look direct."""
    patient = _patient(db, clinic)
    opportunities = _three_open_opportunities(db, clinic, patient, service)
    target = opportunities[0]
    rr.record_action(db, target, "sms")
    db.commit()
    first = target.contacted_at

    rr.record_action(db, target, "zalo")
    db.commit()

    assert target.contacted_at == first
    assert len(db.query(RevenueAction).filter(
        RevenueAction.opportunity_id == target.id).all()) == 2


def test_a_reply_from_the_patient_marks_the_action_answered(db, clinic, service):
    """"Did they reply" is the one funnel step nobody remembers to record, so it
    is read from the patient's own messages rather than asked of staff."""
    patient = _patient(db, clinic)
    opportunities = _three_open_opportunities(db, clinic, patient, service)
    rr.record_action(db, opportunities[0], "zalo")
    db.commit()

    conversation = Conversation(clinic_id=clinic.id, patient_id=patient.id)
    db.add(conversation)
    db.flush()
    db.add(Message(conversation_id=conversation.id, sender="user", content="Dạ em muốn đặt lịch"))
    db.commit()

    assert rr.detect_responses(db, clinic.id) == 1
    action = db.query(RevenueAction).first()
    assert action.status == "responded"
    assert action.responded_at is not None


def test_a_message_sent_before_the_outreach_is_not_a_reply(db, clinic, service):
    """Otherwise every patient who ever wrote to the clinic counts as having
    answered a message that had not been sent yet."""
    patient = _patient(db, clinic)
    conversation = Conversation(clinic_id=clinic.id, patient_id=patient.id)
    db.add(conversation)
    db.flush()
    db.add(Message(conversation_id=conversation.id, sender="user", content="Cho em hỏi giá",
                   created_at=clock.now() - datetime.timedelta(days=10)))
    db.commit()

    opportunities = _three_open_opportunities(db, clinic, patient, service)
    rr.record_action(db, opportunities[0], "zalo")
    db.commit()

    assert rr.detect_responses(db, clinic.id) == 0


# --- the trace ----------------------------------------------------------------

def test_the_chain_leads_from_the_opportunity_to_the_receipt(db, clinic, service):
    """An owner who does not believe a figure has to be able to argue with it."""
    patient = _patient(db, clinic)
    opportunities = _three_open_opportunities(db, clinic, patient, service)
    rr.record_action(db, opportunities[0], "sms", template_code="ZNS_RECALL_01")
    db.commit()

    appt = _appointment(db, clinic, patient, service, days_from_now=2)
    rr.run_detection(db, clinic.id)
    appt.status = "completed"
    db.add(RevenueRecord(clinic_id=clinic.id, patient_id=patient.id,
                         appointment_id=appt.id, amount=2_000_000))
    db.commit()
    rr.run_detection(db, clinic.id)

    won = db.query(RevenueOpportunity).filter(RevenueOpportunity.status == "recovered").one()
    chain = rr.attribution_chain(db, won)

    assert chain["attribution_class"] == rr.DIRECT
    assert chain["actions"][0]["template_code"] == "ZNS_RECALL_01"
    assert chain["appointment"]["id"] == appt.id
    assert chain["revenue_record"]["amount"] == 2_000_000
    assert chain["revenue_recovered"] == 2_000_000


def test_the_chain_shows_no_revenue_rather_than_the_estimate(db, clinic, service):
    """A booked-but-unpaid opportunity must read as empty, not as hopeful."""
    patient = _patient(db, clinic)
    _three_open_opportunities(db, clinic, patient, service)
    _appointment(db, clinic, patient, service, days_from_now=2)
    rr.run_detection(db, clinic.id)

    booked = db.query(RevenueOpportunity).filter(RevenueOpportunity.status == "booked").one()
    chain = rr.attribution_chain(db, booked)

    assert chain["revenue_record"] is None
    assert chain["revenue_recovered"] is None


# --- the funnel ---------------------------------------------------------------

def test_each_funnel_step_is_counted_from_its_own_record(db, clinic, service):
    """Not inferred from the step before, so the drop between two of them is
    real. Contacted 1 -> responded 0 is a finding, not a gap in the data."""
    patient = _patient(db, clinic)
    opportunities = _three_open_opportunities(db, clinic, patient, service)
    for o in opportunities:
        o.is_holdout = False
    rr.record_action(db, opportunities[0], "sms")
    db.commit()

    funnel = rr.recovery_funnel(db, clinic.id)

    assert funnel["detected"] == 3
    assert funnel["contacted"] == 1
    assert funnel["responded"] == 0
    assert funnel["booked"] == 0
