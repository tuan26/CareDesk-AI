"""The rules a revenue engine has to keep, or it becomes a liar.

Every number this feature puts on screen is a claim about the clinic's money.
That makes the failure mode different from the rest of the product: a booking
bug annoys one patient, an inflated "₫186 triệu đang thất thoát" costs the owner
their trust in every other figure CareDesk shows them — and they only have to
check it once.

So these are not tests of the detectors' arithmetic. They are the promises:

  * money already collected is never counted as money to be won back
  * nobody is chased for a treatment the clinic never said repeats
  * the holdout stays held out, and stays on the same side between runs
  * no ROI is claimed while the holdout is too small to support one
  * work a receptionist already did is not undone by the next nightly sweep
"""
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core import clock
from backend.app.core.database import Base
from backend.app.models.models import (
    Appointment, BookingRequest, Branch, Clinic, Doctor, PatientLead,
    PatientPackage, RevenueOpportunity, RevenueRecord, Service, ServicePackage,
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
    branch = Branch(clinic_id=c.id, name="CS1", address="1 Lê Lợi", is_active=True)
    doctor = Doctor(clinic_id=c.id, name="BS An", is_active=True)
    db.add_all([branch, doctor])
    db.flush()
    db.commit()
    return c


@pytest.fixture
def repeating_service(db, clinic):
    """A treatment the clinic has said comes back every 45 days."""
    s = Service(clinic_id=clinic.id, name="Peel da", price=1_500_000,
                duration_minutes=45, revisit_interval_days=45)
    db.add(s)
    db.commit()
    return s


@pytest.fixture
def one_off_service(db, clinic):
    """A treatment with no interval set — the shipped default."""
    s = Service(clinic_id=clinic.id, name="Cắt mí", price=15_000_000, duration_minutes=90)
    db.add(s)
    db.commit()
    return s


def _patient(db, clinic, name="Chị Hoa", phone="0901234567"):
    p = PatientLead(clinic_id=clinic.id, full_name=name, phone=phone)
    db.add(p)
    db.commit()
    return p


def _visit(db, clinic, patient, service, days_ago, status="completed"):
    branch = db.query(Branch).filter(Branch.clinic_id == clinic.id).first()
    doctor = db.query(Doctor).filter(Doctor.clinic_id == clinic.id).first()
    start = clock.now() - datetime.timedelta(days=days_ago)
    appt = Appointment(
        clinic_id=clinic.id, patient_id=patient.id, service_id=service.id,
        doctor_id=doctor.id, branch_id=branch.id, status=status,
        start_time=start, end_time=start + datetime.timedelta(minutes=45),
    )
    db.add(appt)
    db.commit()
    return appt


# --- who gets chased, and who is left alone ---------------------------------

def test_a_patient_past_their_revisit_interval_is_found(db, clinic, repeating_service):
    patient = _patient(db, clinic)
    _visit(db, clinic, patient, repeating_service, days_ago=60)

    rr.run_detection(db, clinic.id)

    found = db.query(RevenueOpportunity).filter(
        RevenueOpportunity.opportunity_type == rr.OVERDUE_REVISIT
    ).all()
    assert len(found) == 1
    assert found[0].estimated_value == 1_500_000
    assert found[0].urgency_days == 15, "quá hạn 15 ngày (60 ngày trước, chu kỳ 45)"


def test_a_service_with_no_interval_never_chases_anyone(db, clinic, one_off_service):
    """The safe default, and the difference between a recall system and a pest.

    A clinic that has not said "cắt mí lặp lại sau N ngày" must never have the
    product decide one for them — a patient messaged about repeating eyelid
    surgery is a complaint, not an opportunity.
    """
    patient = _patient(db, clinic)
    _visit(db, clinic, patient, one_off_service, days_ago=400)

    rr.run_detection(db, clinic.id)

    assert db.query(RevenueOpportunity).count() == 0


def test_someone_with_an_appointment_already_booked_is_not_chased(db, clinic, repeating_service):
    """They are coming. Messaging them to come is the product looking broken."""
    patient = _patient(db, clinic)
    _visit(db, clinic, patient, repeating_service, days_ago=60)
    _visit(db, clinic, patient, repeating_service, days_ago=-3, status="confirmed")

    rr.run_detection(db, clinic.id)

    assert db.query(RevenueOpportunity).filter(
        RevenueOpportunity.opportunity_type == rr.OVERDUE_REVISIT
    ).count() == 0


def test_someone_long_gone_is_left_alone(db, clinic, repeating_service):
    """Past a year they have moved on. Chasing them reads as spam, and the Zalo
    OA it would be sent from is worth more to the clinic than the odds."""
    patient = _patient(db, clinic)
    _visit(db, clinic, patient, repeating_service, days_ago=500)

    rr.run_detection(db, clinic.id)

    assert db.query(RevenueOpportunity).count() == 0


# --- the promise about money already in the till -----------------------------

def test_money_already_paid_is_never_counted_as_recoverable(db, clinic):
    """A package with unused sessions is not revenue waiting to be won.

    The clinic has the cash. What is at risk is delivery, a refund conversation
    and a review — so it is reported in its own bucket and stays out of the
    headline. Adding the two together is the single easiest way to inflate this
    dashboard, which is exactly why it has a test.
    """
    patient = _patient(db, clinic)
    package = ServicePackage(clinic_id=clinic.id, name="Liệu trình mụn 10 buổi",
                             total_sessions=10, price=10_000_000)
    db.add(package)
    db.flush()
    db.add(PatientPackage(
        clinic_id=clinic.id, patient_id=patient.id, package_id=package.id,
        sessions_total=10, sessions_used=2, amount_paid=10_000_000, status="active",
        expires_at=clock.now() + datetime.timedelta(days=10),
    ))
    db.commit()

    rr.run_detection(db, clinic.id)
    summary = rr.leakage_summary(db, clinic.id)

    assert summary["at_risk_delivered"] == 8_000_000, "8 buổi chưa dùng x 1 triệu"
    assert summary["recoverable_gross"] == 0, \
        "tiền khách đã trả không được tính là doanh thu có thể thu hồi"


def test_the_expected_figure_is_never_larger_than_the_gross(db, clinic, repeating_service):
    """Gross is the ceiling; expected is what to plan with. If expected ever
    exceeded gross a probability above 1 had slipped through."""
    for i in range(4):
        patient = _patient(db, clinic, name=f"Khách {i}", phone=f"090000000{i}")
        _visit(db, clinic, patient, repeating_service, days_ago=60)

    rr.run_detection(db, clinic.id)
    summary = rr.leakage_summary(db, clinic.id)

    assert 0 < summary["recoverable_expected"] < summary["recoverable_gross"]


# --- the holdout -------------------------------------------------------------

def test_holdout_assignment_does_not_move_between_runs(db, clinic):
    """Detection re-runs nightly. A coin flip would swap patients between the
    treated and control groups until neither meant anything."""
    first = [rr.assign_holdout(1, pid, rr.OVERDUE_REVISIT) for pid in range(200)]
    second = [rr.assign_holdout(1, pid, rr.OVERDUE_REVISIT) for pid in range(200)]

    assert first == second
    share = sum(first) / len(first)
    assert 0.03 < share < 0.20, f"nhóm đối chứng chiếm {share:.0%}, lệch quá xa 10%"


def test_the_holdout_never_appears_in_the_queue(db, clinic, repeating_service):
    """Not cosmetic: a receptionist who sees the row will ring them, and the
    only means of proving the product works is gone."""
    for i in range(60):
        patient = _patient(db, clinic, name=f"Khách {i}", phone=f"09{i:08d}")
        _visit(db, clinic, patient, repeating_service, days_ago=60)
    rr.run_detection(db, clinic.id)

    held = db.query(RevenueOpportunity).filter(
        RevenueOpportunity.is_holdout == True  # noqa: E712
    ).count()
    assert held > 0, "không có ai trong nhóm đối chứng — phép đo sẽ không bao giờ chạy được"

    queued = rr.money_queue(db, clinic.id, limit=500)
    assert all(not o.is_holdout for o in queued)


def test_no_roi_is_claimed_while_the_holdout_is_too_small(db, clinic, repeating_service):
    """The important refusal. With a handful of controls there is no honest
    lift to report, so the API returns nothing rather than something flattering.
    """
    patient = _patient(db, clinic)
    _visit(db, clinic, patient, repeating_service, days_ago=60)
    rr.run_detection(db, clinic.id)

    performance = rr.recovery_performance(db, clinic.id)

    assert performance["measurable"] is False
    assert performance["net_attributable"] is None
    assert performance["roi"] is None
    assert "đối chứng" in performance["measurable_note"]


def test_gross_recovered_is_reported_even_when_lift_is_not(db, clinic, repeating_service):
    """Refusing the causal claim must not mean showing the clinic a blank page —
    what actually came back after contact is a fact, and is reported as one."""
    patient = _patient(db, clinic)
    _visit(db, clinic, patient, repeating_service, days_ago=60)
    rr.run_detection(db, clinic.id)

    opportunity = db.query(RevenueOpportunity).first()
    opportunity.is_holdout = False
    opportunity.contacted_at = clock.now()
    opportunity.status = "recovered"
    opportunity.recovered_amount = 1_500_000
    db.commit()

    performance = rr.recovery_performance(db, clinic.id)

    assert performance["gross_recovered"] == 1_500_000
    assert performance["measurable"] is False, "một ca không đủ để kết luận nhân quả"


# --- the nightly sweep must not trample the day's work -----------------------

def test_running_detection_twice_creates_nothing_new(db, clinic, repeating_service):
    patient = _patient(db, clinic)
    _visit(db, clinic, patient, repeating_service, days_ago=60)

    rr.run_detection(db, clinic.id)
    rr.run_detection(db, clinic.id)

    assert db.query(RevenueOpportunity).count() == 1


def test_an_opportunity_already_acted_on_is_not_reopened(db, clinic, repeating_service):
    """A receptionist marked it lost this morning. Tonight's sweep must not put
    it back on tomorrow's queue as though nobody had bothered."""
    patient = _patient(db, clinic)
    _visit(db, clinic, patient, repeating_service, days_ago=60)
    rr.run_detection(db, clinic.id)

    opportunity = db.query(RevenueOpportunity).first()
    opportunity.status = "lost"
    opportunity.loss_reason = "price"
    db.commit()

    rr.run_detection(db, clinic.id)
    db.refresh(opportunity)

    assert opportunity.status == "lost"
    assert db.query(RevenueOpportunity).count() == 1


def test_a_patient_who_rebooked_is_closed_as_recovered(db, clinic, repeating_service):
    """Left open, the same visit would be counted as a miss forever and the
    queue would fill with people who already came back."""
    patient = _patient(db, clinic)
    _visit(db, clinic, patient, repeating_service, days_ago=60)
    rr.run_detection(db, clinic.id)

    _visit(db, clinic, patient, repeating_service, days_ago=-2, status="confirmed")
    rr.run_detection(db, clinic.id)

    opportunity = db.query(RevenueOpportunity).first()
    assert opportunity.status == "recovered"
    assert opportunity.resolved_appointment_id is not None


# --- the numbers explain themselves ------------------------------------------

def test_probability_is_never_a_certainty_and_never_zero(db, clinic, repeating_service):
    patient = _patient(db, clinic, phone=None)
    _visit(db, clinic, patient, repeating_service, days_ago=60)
    rr.run_detection(db, clinic.id)

    opportunity = db.query(RevenueOpportunity).first()
    assert 0 < opportunity.probability < 1


def test_every_probability_carries_its_reasons(db, clinic, repeating_service):
    """A number nobody can interrogate gets ignored the first time one entry
    looks wrong — and one entry always looks wrong."""
    patient = _patient(db, clinic, phone=None)
    _visit(db, clinic, patient, repeating_service, days_ago=60)
    rr.run_detection(db, clinic.id)

    reasons = db.query(RevenueOpportunity).first().reasons
    codes = {r["code"] for r in reasons}
    assert "base_rate" in codes
    assert "no_phone" in codes, "không có số điện thoại là lý do lớn nhất, phải nêu ra"


def test_an_unmeasured_rate_is_labelled_as_an_assumption(db, clinic):
    """Until the clinic has its own numbers the figure is a guess, and the
    screen has to say so rather than presenting it as a finding."""
    rate, measured = rr.observed_rate(db, clinic.id, rr.OVERDUE_REVISIT)

    assert rate == rr.BASE_RATES[rr.OVERDUE_REVISIT]
    assert measured is False


def test_the_draft_message_never_gives_away_a_discount(db, clinic, repeating_service):
    """The product does not get to spend the clinic's margin. An offer is the
    owner's decision, made per campaign, never baked into a template."""
    patient = _patient(db, clinic)
    _visit(db, clinic, patient, repeating_service, days_ago=60)
    rr.run_detection(db, clinic.id)

    opportunity = db.query(RevenueOpportunity).first()
    text = opportunity.recommended_message.lower()

    assert opportunity.recommended_offer is None
    assert not any(word in text for word in ("giảm", "khuyến mãi", "ưu đãi", "%")), text
    assert "Hoa" in opportunity.recommended_message, "tin nhắn phải gọi đúng tên khách"


@pytest.mark.parametrize("stored, greeting", [
    ("Trịnh Thị Hoa (tên mới)", "Hoa"),
    ("Nguyễn Văn An - khách cũ", "An"),
    ("Lê Thị Hoa [Zalo]", "Hoa"),
    ("phương uyên", "uyên"),
    ("0912345678", "anh/chị"),
    ("", "anh/chị"),
])
def test_notes_a_receptionist_typed_after_the_name_never_reach_the_patient(stored, greeting):
    """Found by running it, not by reading it.

    Reception writes "(tên mới)" or "- khách cũ" after a name to tell two
    records apart. Taking the last word opened a real draft with "Chào mới)",
    which tells the patient exactly how they are stored. Falling back to
    "anh/chị" is impersonal; a fragment is insulting.
    """
    assert rr._first_name(stored) == greeting


# --- the other detectors -----------------------------------------------------

def test_a_booking_request_nobody_rang_back_is_found(db, clinic, repeating_service):
    """The most embarrassing row on the dashboard and the cheapest to fix: the
    patient already said yes."""
    patient = _patient(db, clinic)
    db.add(BookingRequest(
        clinic_id=clinic.id, patient_id=patient.id, service_id=repeating_service.id,
        service_or_need="Peel da", full_name=patient.full_name,
        contact_value=patient.phone, status="requested",
        created_at=clock.now() - datetime.timedelta(days=5),
    ))
    db.commit()

    rr.run_detection(db, clinic.id)

    found = db.query(RevenueOpportunity).filter(
        RevenueOpportunity.opportunity_type == rr.LOST_BOOKING
    ).one()
    assert found.estimated_value == 1_500_000
    assert found.urgency_days == 5


def test_a_fresh_booking_request_is_not_treated_as_lost(db, clinic, repeating_service):
    """Reception has not had a chance yet. Flagging it as leakage within the
    hour teaches staff the dashboard cries wolf."""
    patient = _patient(db, clinic)
    db.add(BookingRequest(
        clinic_id=clinic.id, patient_id=patient.id, service_id=repeating_service.id,
        service_or_need="Peel da", full_name=patient.full_name,
        contact_value=patient.phone, status="requested", created_at=clock.now(),
    ))
    db.commit()

    rr.run_detection(db, clinic.id)

    assert db.query(RevenueOpportunity).filter(
        RevenueOpportunity.opportunity_type == rr.LOST_BOOKING
    ).count() == 0


def test_a_no_show_who_never_came_back_is_found(db, clinic, repeating_service):
    patient = _patient(db, clinic)
    _visit(db, clinic, patient, repeating_service, days_ago=30, status="no_show")

    rr.run_detection(db, clinic.id)

    assert db.query(RevenueOpportunity).filter(
        RevenueOpportunity.opportunity_type == rr.NO_SHOW_RECOVERY
    ).count() == 1


def test_a_no_show_who_rebooked_is_not_chased(db, clinic, repeating_service):
    patient = _patient(db, clinic)
    _visit(db, clinic, patient, repeating_service, days_ago=30, status="no_show")
    _visit(db, clinic, patient, repeating_service, days_ago=10, status="completed")

    rr.run_detection(db, clinic.id)

    assert db.query(RevenueOpportunity).filter(
        RevenueOpportunity.opportunity_type == rr.NO_SHOW_RECOVERY
    ).count() == 0


# --- the queue's ordering ----------------------------------------------------

def test_the_queue_puts_the_bigger_expected_value_first(db, clinic):
    """"Sorted by value" is the whole reason a receptionist would open this
    instead of working down a list of names."""
    cheap = Service(clinic_id=clinic.id, name="Soi da", price=200_000,
                    duration_minutes=15, revisit_interval_days=30)
    dear = Service(clinic_id=clinic.id, name="Laser CO2", price=8_000_000,
                   duration_minutes=60, revisit_interval_days=30)
    db.add_all([cheap, dear])
    db.commit()

    small = _patient(db, clinic, name="Khách Nhỏ", phone="0900000001")
    big = _patient(db, clinic, name="Khách Lớn", phone="0900000002")
    _visit(db, clinic, small, cheap, days_ago=40)
    _visit(db, clinic, big, dear, days_ago=40)

    rr.run_detection(db, clinic.id)
    queue = rr.money_queue(db, clinic.id)

    assert queue[0].patient_id == big.id, "việc đáng tiền nhất phải nằm trên đầu"


def test_a_package_expiring_this_week_outranks_one_expiring_next_month(db, clinic):
    """Urgency is not "how long ago" but "how much does today beat next week"."""
    soon = RevenueOpportunity(clinic_id=clinic.id, patient_id=1,
                              opportunity_type=rr.PACKAGE_EXPIRING, dedupe_key="1",
                              estimated_value=5_000_000, probability=0.3, urgency_days=5)
    later = RevenueOpportunity(clinic_id=clinic.id, patient_id=2,
                               opportunity_type=rr.PACKAGE_EXPIRING, dedupe_key="2",
                               estimated_value=5_000_000, probability=0.3, urgency_days=28)

    assert rr.score(soon) > rr.score(later)
