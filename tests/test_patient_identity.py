"""Who the patient is, and which doctor they asked for.

Three defects that all end the same way — the clinic acting on the wrong person
or the wrong doctor, and finding out in the waiting room.

  * A patient who asked for Bác sĩ Lê Thị B was booked with Bác sĩ Nguyễn Văn A.
    Their choice was never read: the flow took the first doctor with a free slot.
  * The booking form created a new patient record on every submission, so one
    person booking twice became two rows in the CRM with split history.
  * A returning phone number kept whatever name was typed the first time, for
    ever — which had a real patient booked under "Popup Test".
"""
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models.models import (
    BookingRequest, Branch, Clinic, Conversation, Doctor, PatientLead, Service,
    WorkingSchedule,
)
from backend.app.services.booking_flow import _resolve_doctor, handle_booking
from backend.app.services.patients import upsert_lead

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
def setup(db):
    """Two doctors, both working every day at the same branch."""
    clinic = Clinic(name="CareDesk", is_active=True)
    db.add(clinic)
    db.flush()
    branch = Branch(clinic_id=clinic.id, name="Quận 10", address="123 Ba Tháng Hai",
                    is_active=True)
    db.add(branch)
    db.flush()
    service = Service(clinic_id=clinic.id, name="Điều trị mụn Chuẩn Y Khoa",
                      price=450000, duration_minutes=45)
    doctor_a = Doctor(clinic_id=clinic.id, name="Bác sĩ Nguyễn Văn A",
                      specialty="Da liễu", branch_id=branch.id, is_active=True)
    doctor_b = Doctor(clinic_id=clinic.id, name="Bác sĩ Lê Thị B",
                      specialty="Thẩm mỹ da", branch_id=branch.id, is_active=True)
    patient = PatientLead(clinic_id=clinic.id, full_name="Trịnh Thị Hoa", phone="0912202303")
    db.add_all([service, doctor_a, doctor_b, patient])
    db.flush()
    for doctor in (doctor_a, doctor_b):
        for day in range(7):
            db.add(WorkingSchedule(doctor_id=doctor.id, branch_id=branch.id, day_of_week=day,
                                   start_time=datetime.time(8, 0), end_time=datetime.time(18, 0)))
    conv = Conversation(clinic_id=clinic.id, patient_id=patient.id, branch_id=branch.id,
                        booking_state={"active": True, "service_id": service.id,
                                       "full_name": "Trịnh Thị Hoa", "phone": "0912202303"})
    db.add(conv)
    db.commit()
    return {"clinic": clinic, "branch": branch, "service": service,
            "a": doctor_a, "b": doctor_b, "conv": conv, "patient": patient}


# --- the doctor the patient actually asked for -------------------------------

def test_a_named_doctor_is_recognised(db, setup):
    """The message from the report, verbatim."""
    found = _resolve_doctor(db, setup["clinic"].id,
                            "cho tôi Bác sĩ Lê Thị B — Thẩm mỹ da / Điều trị mụn")

    assert found is not None and found.id == setup["b"].id


def test_a_name_typed_without_diacritics_still_matches(db, setup):
    assert _resolve_doctor(db, setup["clinic"].id, "cho minh bac si le thi b").id == setup["b"].id


def test_a_message_naming_nobody_resolves_to_nobody(db, setup):
    """"chị B" is not enough to book someone's afternoon on."""
    assert _resolve_doctor(db, setup["clinic"].id, "tôi muốn đặt lịch trị mụn") is None


def test_the_request_records_the_doctor_the_patient_chose(db, setup):
    """The whole bug: asked for B, booked with A."""
    handle_booking(db, setup["conv"], "cho tôi Bác sĩ Lê Thị B")
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    handle_booking(db, setup["conv"], tomorrow.strftime("ngày %d/%m/%Y"))
    handle_booking(db, setup["conv"], "1")

    request = db.query(BookingRequest).first()
    assert request is not None
    assert request.doctor_id == setup["b"].id, "đặt cho bác sĩ khác với người khách chọn"


def test_choosing_a_doctor_is_confirmed_back_to_the_patient(db, setup):
    """So they can see it landed, instead of discovering otherwise on the day."""
    reply = handle_booking(db, setup["conv"], "cho tôi Bác sĩ Lê Thị B")

    assert "Lê Thị B" in reply


def test_a_busy_doctor_is_not_swapped_for_a_free_colleague(db, setup):
    """Silently substituting is how a patient ends up in front of someone they
    did not pick. Say whose diary is full and let them choose."""
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    # B works nowhere tomorrow; A still does.
    db.query(WorkingSchedule).filter(
        WorkingSchedule.doctor_id == setup["b"].id,
        WorkingSchedule.day_of_week == tomorrow.weekday()).delete()
    db.commit()

    handle_booking(db, setup["conv"], "cho tôi Bác sĩ Lê Thị B")
    reply = handle_booking(db, setup["conv"], tomorrow.strftime("ngày %d/%m/%Y"))

    assert "Lê Thị B" in reply, reply
    assert db.query(BookingRequest).count() == 0
    # And no slot list belonging to the other doctor.
    assert "1." not in reply


# --- one patient per phone number --------------------------------------------

def test_a_returning_number_reuses_the_same_record(db, setup):
    """The booking form created a new row every submission: one person booking
    twice became two patients, with split history and split attribution."""
    first = upsert_lead(db, setup["clinic"].id, "Trịnh Thị Hoa", "0912202303", "web_form")
    db.commit()
    second = upsert_lead(db, setup["clinic"].id, "Trịnh Thị Hoa", "0912202303", "web_form")
    db.commit()

    assert first.id == second.id
    assert db.query(PatientLead).filter(PatientLead.phone == "0912202303").count() == 1


def test_the_newer_name_wins(db, setup):
    """People correct typos and get married. Keeping the first name for ever is
    what had someone booked under a name typed into a test form weeks earlier."""
    upsert_lead(db, setup["clinic"].id, "Trinh Thi Hoa", "0912202303", "web")
    db.commit()
    lead = upsert_lead(db, setup["clinic"].id, "Trịnh Thị Hoa", "0912202303", "web")
    db.commit()

    assert lead.full_name == "Trịnh Thị Hoa"


def test_a_blank_name_never_overwrites_a_real_one(db, setup):
    upsert_lead(db, setup["clinic"].id, "Trịnh Thị Hoa", "0912202303", "web")
    db.commit()
    lead = upsert_lead(db, setup["clinic"].id, "   ", "0912202303", "web")

    assert lead.full_name == "Trịnh Thị Hoa"


def test_two_clinics_sharing_a_number_are_two_patients(db, setup):
    """Crossing that boundary would leak one tenant's records into another's."""
    other = Clinic(name="Phòng khám khác", is_active=True)
    db.add(other)
    db.flush()

    theirs = upsert_lead(db, other.id, "Trịnh Thị Hoa", "0912202303", "web")
    db.commit()

    assert theirs.id != setup["patient"].id


def test_the_patient_can_take_the_offered_alternative(db, setup):
    """The reply offers "ngày khác, hay bác sĩ khác?" — and the second half had
    no handler, so a patient who agreed to it sat in the same question for
    ever."""
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    db.query(WorkingSchedule).filter(
        WorkingSchedule.doctor_id == setup["b"].id,
        WorkingSchedule.day_of_week == tomorrow.weekday()).delete()
    db.commit()

    handle_booking(db, setup["conv"], "cho tôi Bác sĩ Lê Thị B")
    handle_booking(db, setup["conv"], tomorrow.strftime("ngày %d/%m/%Y"))
    reply = handle_booking(db, setup["conv"], "bác sĩ khác cũng được")

    # The day they already chose is kept: releasing the doctor should produce
    # times, not send them back to "ngày nào ạ?".
    assert reply is not None and "khung giờ" in reply.lower(), reply
    db.refresh(setup["conv"])
    assert not setup["conv"].booking_state.get("doctor_requested")


def test_releasing_the_doctor_is_not_mistaken_for_chatter(db, setup):
    """It carries no service, date, phone or name, so the mid-flow guard would
    hand it to the assistant and the pin would never come off."""
    handle_booking(db, setup["conv"], "cho tôi Bác sĩ Lê Thị B")

    assert handle_booking(db, setup["conv"], "bác sĩ nào cũng được ạ") is not None
