"""Do patients come back — measured so the answer can actually change.

The number this replaces was a running total of everyone who had ever visited
twice. It only ever went up, so a three-year-old clinic showed a big figure
whether CareDesk helped or not. A metric that cannot fall cannot prove anything,
and this one is meant to justify a subscription.
"""
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models.models import (
    Appointment, Branch, Clinic, Doctor, PatientLead, Service,
)
from backend.app.services.retention import (
    DEFAULT_RETURN_WINDOW_DAYS, MIN_COHORT_FOR_CONFIDENCE, return_rate,
)

engine = create_engine("sqlite:///:memory:")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

NOW = datetime.datetime(2026, 8, 12, 10, 0)


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
    branch = Branch(clinic_id=c.id, name="CS1", address="1 A", is_active=True)
    service = Service(clinic_id=c.id, name="Tri mun", price=500000, duration_minutes=30)
    doctor = Doctor(clinic_id=c.id, name="BS A", is_active=True)
    db.add_all([branch, service, doctor])
    db.commit()
    return {"clinic": c, "branch": branch, "service": service, "doctor": doctor}


def _visit(db, clinic, patient, days_ago, status="completed"):
    start = NOW - datetime.timedelta(days=days_ago)
    a = Appointment(clinic_id=clinic["clinic"].id, branch_id=clinic["branch"].id,
                    service_id=clinic["service"].id, doctor_id=clinic["doctor"].id,
                    patient_id=patient.id, status=status,
                    start_time=start, end_time=start + datetime.timedelta(minutes=30))
    db.add(a)
    db.commit()
    return a


def _patient(db, clinic, name):
    p = PatientLead(clinic_id=clinic["clinic"].id, full_name=name, consent_given=True)
    db.add(p)
    db.commit()
    return p


def _rate(db, clinic):
    return return_rate(db, clinic["clinic"].id, now=NOW)


# --- the core calculation ----------------------------------------------------

def test_a_patient_who_came_back_counts(db, clinic):
    p = _patient(db, clinic, "Quay lai")
    _visit(db, clinic, p, days_ago=150)   # first visit, cohort window
    _visit(db, clinic, p, days_ago=130)   # returned 20 days later

    r = _rate(db, clinic)
    assert r.cohort_size == 1
    assert r.returned == 1
    assert r.percent == 100.0


def test_a_patient_who_never_came_back_counts_against(db, clinic):
    p = _patient(db, clinic, "Mot lan")
    _visit(db, clinic, p, days_ago=150)

    r = _rate(db, clinic)
    assert r.cohort_size == 1 and r.returned == 0 and r.percent == 0.0


def test_the_rate_is_a_percentage_of_the_cohort(db, clinic):
    for i in range(4):
        p = _patient(db, clinic, f"Khach {i}")
        _visit(db, clinic, p, days_ago=150)
        if i < 1:
            _visit(db, clinic, p, days_ago=140)

    r = _rate(db, clinic)
    assert r.cohort_size == 4 and r.returned == 1 and r.percent == 25.0


# --- only mature cohorts, which is what makes it honest ----------------------

def test_a_patient_who_has_not_had_time_to_return_is_excluded(db, clinic):
    """Someone who first came last Tuesday has not had ninety days. Counting
    them would drag the rate down every time the clinic wins a new patient —
    exactly backwards for a metric meant to reward growth."""
    recent = _patient(db, clinic, "Vua den")
    _visit(db, clinic, recent, days_ago=5)

    r = _rate(db, clinic)
    assert r.cohort_size == 0
    assert r.percent is None, "không đủ dữ liệu thì không được bịa ra một con số"


def test_returning_after_the_window_does_not_count(db, clinic):
    p = _patient(db, clinic, "Quay lai muon")
    _visit(db, clinic, p, days_ago=170)
    _visit(db, clinic, p, days_ago=20)    # 150 days later, past the window

    r = _rate(db, clinic)
    assert r.cohort_size == 1 and r.returned == 0


def test_a_long_standing_patient_is_not_a_first_timer(db, clinic):
    """Their earliest visit predates the cohort window, so they are not new —
    counting them would let an old clinic inflate the rate with regulars."""
    p = _patient(db, clinic, "Khach cu")
    _visit(db, clinic, p, days_ago=800)
    _visit(db, clinic, p, days_ago=150)
    _visit(db, clinic, p, days_ago=140)

    assert _rate(db, clinic).cohort_size == 0


# --- what counts as a visit --------------------------------------------------

def test_only_completed_visits_count(db, clinic):
    """A booking nobody attended says nothing about whether they came back."""
    p = _patient(db, clinic, "Khong den")
    _visit(db, clinic, p, days_ago=150)
    _visit(db, clinic, p, days_ago=140, status="no_show")
    _visit(db, clinic, p, days_ago=135, status="cancelled")

    r = _rate(db, clinic)
    assert r.cohort_size == 1 and r.returned == 0


def test_another_clinics_patients_are_invisible(db, clinic):
    other = Clinic(name="Khac", is_active=True)
    db.add(other)
    db.flush()
    p = PatientLead(clinic_id=other.id, full_name="Nguoi khac", consent_given=True)
    db.add(p)
    db.flush()
    start = NOW - datetime.timedelta(days=150)
    db.add(Appointment(clinic_id=other.id, branch_id=clinic["branch"].id,
                       service_id=clinic["service"].id, doctor_id=clinic["doctor"].id,
                       patient_id=p.id, status="completed",
                       start_time=start, end_time=start + datetime.timedelta(minutes=30)))
    db.commit()

    assert _rate(db, clinic).cohort_size == 0


# --- honesty about small numbers ---------------------------------------------

def test_a_small_cohort_is_flagged_as_unreliable(db, clinic):
    """With three patients, one of them moves the figure by 33 points. Showing
    that as a headline percentage invites an argument at the next review."""
    for i in range(3):
        p = _patient(db, clinic, f"K{i}")
        _visit(db, clinic, p, days_ago=150)

    r = _rate(db, clinic)
    assert r.cohort_size == 3
    assert r.is_reliable is False


def test_a_large_enough_cohort_is_reliable(db, clinic):
    for i in range(MIN_COHORT_FOR_CONFIDENCE):
        p = _patient(db, clinic, f"K{i}")
        _visit(db, clinic, p, days_ago=150)

    assert _rate(db, clinic).is_reliable is True


def test_an_empty_clinic_returns_no_percentage_rather_than_zero(db, clinic):
    r = _rate(db, clinic)
    assert r.percent is None and r.cohort_size == 0


def test_the_window_is_reported_so_the_number_can_be_explained(db, clinic):
    r = _rate(db, clinic)
    assert r.window_days == DEFAULT_RETURN_WINDOW_DAYS
    assert r.cohort_start < r.cohort_end
