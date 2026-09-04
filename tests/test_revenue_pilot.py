"""What a controlled pilot has to be able to prove, and what it must not fake.

Two failure modes are specific to a pilot and neither shows up as an error.

The first is a pilot that quietly runs with its largest detector switched off.
Nobody sets a revisit interval, ``overdue_revisit`` finds nothing, and everyone
concludes the engine cannot find much — when the truth is that it was never
given the one number it cannot infer.

The second is a recovery rate computed over the wrong sample. Package
opportunities are already paid for and can never be "recovered"; leaving them in
the denominator makes the clinic look worse than it is, and quietly moving them
to the numerator would make it look better than it is. Either way the headline
percentage stops meaning anything.
"""
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core import clock
from backend.app.core.database import Base
from backend.app.models.models import (
    Branch, Clinic, Doctor, PatientLead, PatientPackage, RevenueOpportunity,
    Service, ServicePackage,
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


def _opportunity(db, clinic, kind=rr.LOST_BOOKING, value=1_000_000, **kwargs):
    patient = PatientLead(clinic_id=clinic.id, full_name="Khách", phone="09")
    db.add(patient)
    db.flush()
    o = RevenueOpportunity(
        clinic_id=clinic.id, patient_id=patient.id, opportunity_type=kind,
        dedupe_key=str(patient.id), estimated_value=value, probability=0.25,
        **kwargs)
    db.add(o)
    db.commit()
    return o


# --- the interval nobody can infer -------------------------------------------

def test_a_clinic_with_no_intervals_is_told_the_detector_is_blind(db, clinic):
    """The quiet pilot failure, caught by a field rather than by someone
    noticing an empty screen weeks later."""
    db.add(Service(clinic_id=clinic.id, name="Trị mụn", price=500_000, duration_minutes=30))
    db.commit()

    readiness = rr.recovery_readiness(db, clinic.id)

    assert readiness["overdue_revisit_enabled"] is False
    assert readiness["needs_attention"] is True
    assert "không tự đoán" in readiness["message"]


def test_a_clinic_whose_work_never_repeats_can_still_finish(db, clinic):
    """"No interval set" and "nothing here repeats" are identical in the data.
    Without a way to say the second, such a clinic is nagged forever — or
    invents a number to silence the warning, which is the one input the recall
    engine must never be given."""
    db.add(Service(clinic_id=clinic.id, name="Cắt mí", price=15_000_000, duration_minutes=90))
    clinic.revisit_intervals_reviewed_at = clock.now()
    db.commit()

    readiness = rr.recovery_readiness(db, clinic.id)

    assert readiness["needs_attention"] is False
    assert readiness["overdue_revisit_enabled"] is False, "vẫn không có chu kỳ nào, và đó là đúng"


def test_setting_one_interval_switches_the_detector_on(db, clinic):
    db.add(Service(clinic_id=clinic.id, name="Trị mụn", price=500_000,
                   duration_minutes=30, revisit_interval_days=30))
    db.commit()

    readiness = rr.recovery_readiness(db, clinic.id)

    assert readiness["overdue_revisit_enabled"] is True
    assert readiness["needs_attention"] is False


@pytest.mark.parametrize("name, expected", [
    ("Tiêm Botox vùng trán", 90),
    ("Điều trị mụn Chuẩn Y Khoa", 30),
    ("Laser Fractional CO2 trị sẹo rỗ", 45),
    ("Filler má baby", 180),
    ("Cắt mí Hàn Quốc", None),
])
def test_a_suggestion_is_offered_but_only_where_one_is_known(name, expected):
    """Silence where nothing is known matters as much as the suggestions: an
    eyelid surgery with a confident "90 ngày" beside it invites exactly the
    wrong number."""
    assert rr.suggest_revisit_days(name) == expected


def test_suggestions_are_never_written_by_the_system(db, clinic):
    """The whole principle in one assertion. A suggestion the clinic accepts is
    a prompt; one applied on their behalf is the engine deciding who gets
    chased."""
    service = Service(clinic_id=clinic.id, name="Tiêm Botox", price=5_000_000,
                      duration_minutes=30)
    db.add(service)
    db.commit()

    assert rr.suggest_revisit_days(service.name) == 90
    rr.run_detection(db, clinic.id)
    db.refresh(service)

    assert service.revisit_interval_days is None, "gợi ý đã bị ghi vào dữ liệu"


# --- did the engine find the right misses ------------------------------------

def test_precision_is_none_until_staff_have_judged_anything(db, clinic):
    """It cannot be computed, only asked. Producing a number here would be the
    system marking its own homework."""
    _opportunity(db, clinic)

    scorecard = rr.pilot_scorecard(db, clinic.id)

    assert scorecard["detection_precision"] is None
    assert "tìm được nhiều" in scorecard["precision_note"]


def test_precision_counts_yes_against_no_and_leaves_unsure_out(db, clinic):
    """Unsure is a real answer. Forcing it to a side would make the number look
    firmer than the evidence behind it."""
    for verdict in ("yes", "yes", "yes", "no", "unsure"):
        rr.judge_opportunity(_opportunity(db, clinic), verdict)
    db.commit()

    scorecard = rr.pilot_scorecard(db, clinic.id)

    assert scorecard["judged"] == 4
    assert scorecard["judged_unsure"] == 1
    assert scorecard["detection_precision"] == 0.75


def test_an_opportunity_can_be_judged_real_even_though_it_was_lost(db, clinic):
    """The distinction the metric exists for. A real miss that refused to come
    back is a detector working and a patient saying no — not a bad detection."""
    opportunity = _opportunity(db, clinic, status="lost", loss_reason="price")
    rr.judge_opportunity(opportunity, "yes")
    db.commit()

    assert rr.pilot_scorecard(db, clinic.id)["detection_precision"] == 1.0


# --- the recovery rate sample -------------------------------------------------

def test_package_opportunities_stay_out_of_the_recovery_rate(db, clinic):
    """They were paid for months ago. In the denominator they make the clinic
    look worse than it is; in the numerator, better. Neither is true."""
    _opportunity(db, clinic, kind=rr.PACKAGE_EXPIRING, value=8_000_000,
                 status="lost", loss_reason="timing")
    _opportunity(db, clinic, kind=rr.LOST_BOOKING, value=1_000_000,
                 status="recovered", recovered_amount=1_000_000)
    db.commit()

    scorecard = rr.pilot_scorecard(db, clinic.id)

    assert scorecard["sample_size"] == 1
    assert scorecard["opportunity_value"] == 1_000_000
    assert scorecard["recovery_rate"] == 1.0


def test_the_holdout_stays_out_of_the_recovery_rate(db, clinic):
    """Nobody contacted them, so their outcome says nothing about how well the
    recovery work is going. They are the comparison, not part of the score."""
    _opportunity(db, clinic, status="lost", loss_reason="timing", is_holdout=True)
    _opportunity(db, clinic, status="recovered", recovered_amount=1_000_000)
    db.commit()

    assert rr.pilot_scorecard(db, clinic.id)["sample_size"] == 1


def test_unresolved_opportunities_do_not_drag_the_rate_down(db, clinic):
    """Still open means not yet an answer. Counting them as failures would make
    every rate start at zero and climb only as the backlog closes."""
    _opportunity(db, clinic, status="open")
    _opportunity(db, clinic, status="contacted", contacted_at=clock.now())
    _opportunity(db, clinic, status="recovered", recovered_amount=800_000)
    db.commit()

    scorecard = rr.pilot_scorecard(db, clinic.id)

    assert scorecard["sample_size"] == 1
    assert scorecard["recovery_rate"] == 0.8


def test_the_rate_is_not_capped_when_patients_pay_more_than_expected(db, clinic):
    """Above 100% is a finding — the estimates are low. Capping it would hide
    exactly the thing worth knowing."""
    _opportunity(db, clinic, value=1_000_000, status="recovered",
                 recovered_amount=1_500_000)
    db.commit()

    assert rr.pilot_scorecard(db, clinic.id)["recovery_rate"] == 1.5


def test_revenue_per_opportunity_divides_by_everything_detected(db, clinic):
    """The pricing number. Dividing by winners only would answer "what does a
    win pay", which nobody needs — the question is what one detected
    opportunity has been worth, misses included."""
    _opportunity(db, clinic, status="recovered", recovered_amount=2_000_000)
    _opportunity(db, clinic, status="lost", loss_reason="price")
    _opportunity(db, clinic, status="open")
    db.commit()

    scorecard = rr.pilot_scorecard(db, clinic.id)

    assert scorecard["revenue_per_opportunity"] == pytest.approx(2_000_000 / 3)


def test_superseded_opportunities_are_outside_every_pilot_figure(db, clinic):
    """Already excluded from revenue and conversion; the scorecard must not
    quietly let them back in through a different denominator."""
    _opportunity(db, clinic, status="superseded")
    _opportunity(db, clinic, status="recovered", recovered_amount=1_000_000)
    db.commit()

    scorecard = rr.pilot_scorecard(db, clinic.id)

    assert scorecard["detected"] == 1
    assert scorecard["revenue_per_opportunity"] == 1_000_000


def test_an_empty_pilot_reports_nothing_rather_than_zero(db, clinic):
    """A rate of 0% reads as "the engine is failing"; None reads as "no data
    yet". At the start of a pilot only the second is true."""
    scorecard = rr.pilot_scorecard(db, clinic.id)

    assert scorecard["recovery_rate"] is None
    assert scorecard["revenue_per_opportunity"] is None
    assert scorecard["detection_precision"] is None


# --- the revenue step must not take the clinic offline -----------------------

def test_the_revisit_step_never_blocks_the_public_link():
    """It briefly did. "Which steps block going live" was defined in two places
    and only one of them learned about the new step, so a clinic could be kept
    off the internet by a revenue setting that has nothing to do with whether
    their booking page works.
    """
    from backend.app.api.endpoints.onboarding import NON_BLOCKING_STEPS

    assert "revisit" in NON_BLOCKING_STEPS


def test_going_live_and_revenue_readiness_are_reported_separately():
    """Not blocking must not mean invisible: a pilot that starts with its
    largest detector switched off and nobody noticing is the failure this whole
    step exists to prevent."""
    import inspect

    from backend.app.api.endpoints import onboarding

    source = inspect.getsource(onboarding.onboarding_status)
    assert "revenue_recovery_ready" in source
