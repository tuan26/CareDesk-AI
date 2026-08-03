"""The branch a patient picks must be the branch they get booked into."""
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models.models import (
    Branch, Clinic, Conversation, Doctor, PatientLead, WorkingSchedule,
)
from backend.app.services.ai_engine import build_clinic_identity
from backend.app.services.booking_flow import (
    _branch_ever_open, _other_open_branches, _pick_doctor_and_slots,
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
    """One clinic, three locations: two staffed, one with no schedule at all."""
    c = Clinic(name="CareDesk", is_active=True)
    db.add(c)
    db.flush()

    q10 = Branch(clinic_id=c.id, name="Quan 10", address="1 A", is_active=True)
    q1 = Branch(clinic_id=c.id, name="Quan 1", address="2 B", is_active=True)
    bm = Branch(clinic_id=c.id, name="Bach Mai", address="3 C", is_active=True)
    db.add_all([q10, q1, bm])
    db.flush()

    d1 = Doctor(clinic_id=c.id, name="BS Mot", branch_id=q10.id, is_active=True)
    d2 = Doctor(clinic_id=c.id, name="BS Hai", branch_id=bm.id, is_active=True)
    d3 = Doctor(clinic_id=c.id, name="BS Ba", branch_id=q1.id, is_active=True)
    db.add_all([d1, d2, d3])
    db.flush()

    for day in range(7):  # both staffed branches open every day
        db.add(WorkingSchedule(doctor_id=d1.id, branch_id=q10.id, day_of_week=day,
                               start_time=datetime.time(8, 0), end_time=datetime.time(17, 0)))
        db.add(WorkingSchedule(doctor_id=d2.id, branch_id=bm.id, day_of_week=day,
                               start_time=datetime.time(8, 0), end_time=datetime.time(17, 0)))
    # q1 deliberately gets no WorkingSchedule
    db.commit()
    return {"clinic": c, "q10": q10, "q1": q1, "bm": bm, "d1": d1, "d2": d2}


def _tomorrow():
    return datetime.date.today() + datetime.timedelta(days=1)


def test_booking_uses_the_branch_the_patient_picked(db, clinic):
    """Regression: this used to return the first doctor found, so every booking
    landed on whichever branch that doctor worked at."""
    doctor, branch, slots = _pick_doctor_and_slots(
        db, clinic["clinic"].id, _tomorrow(), 30, branch_id=clinic["bm"].id)
    assert slots
    assert branch.id == clinic["bm"].id
    assert doctor.id == clinic["d2"].id


def test_each_branch_resolves_to_its_own_doctor(db, clinic):
    _, b1, _ = _pick_doctor_and_slots(db, clinic["clinic"].id, _tomorrow(), 30,
                                      branch_id=clinic["q10"].id)
    _, b2, _ = _pick_doctor_and_slots(db, clinic["clinic"].id, _tomorrow(), 30,
                                      branch_id=clinic["bm"].id)
    assert b1.id != b2.id


def test_unpinned_booking_still_works(db, clinic):
    """No branch chosen -> any staffed branch is acceptable."""
    doctor, branch, slots = _pick_doctor_and_slots(db, clinic["clinic"].id, _tomorrow(), 30)
    assert slots and doctor and branch


def test_branch_without_schedule_offers_no_slots(db, clinic):
    _, _, slots = _pick_doctor_and_slots(db, clinic["clinic"].id, _tomorrow(), 30,
                                         branch_id=clinic["q1"].id)
    assert slots == []
    assert _branch_ever_open(db, clinic["q1"].id) is False
    assert _branch_ever_open(db, clinic["bm"].id) is True


def test_dead_end_branch_suggests_the_open_ones(db, clinic):
    others = _other_open_branches(db, clinic["clinic"].id, clinic["q1"].id)
    names = {b.name for b in others}
    assert names == {"Quan 10", "Bach Mai"}


def test_ai_context_names_the_chosen_branch(db, clinic):
    """Otherwise "địa chỉ ở đâu" gets answered with every branch at once."""
    text = build_clinic_identity(db, clinic["clinic"], branch_id=clinic["bm"].id)
    assert "Bach Mai" in text
    head = text.split("Các cơ sở khác:")[0]
    assert "Bach Mai" in head and "Quan 10" not in head

    plain = build_clinic_identity(db, clinic["clinic"])
    assert "KHÁCH ĐANG HỎI VỀ CƠ SỞ" not in plain


def test_conversation_stores_the_branch(db, clinic):
    p = PatientLead(clinic_id=clinic["clinic"].id, full_name="A", consent_given=True)
    db.add(p)
    db.flush()
    conv = Conversation(clinic_id=clinic["clinic"].id, patient_id=p.id,
                        branch_id=clinic["bm"].id, channel="web")
    db.add(conv)
    db.commit()
    assert db.query(Conversation).first().branch_id == clinic["bm"].id
