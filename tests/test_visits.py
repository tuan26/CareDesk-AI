"""The queue and the visit record.

The queue exists as much for adoption as for function: the clearest signal a
pilot is working is whether staff open the product without being told, and
"who is here right now" is the only screen that earns a daily open.

The record is deliberately light — no prescriptions. Photos are the part that
carries weight for dermatology and aesthetics, and they are photographs of
patients, so how they are stored and served is treated as a security question
rather than a storage one.
"""
import datetime
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.database import Base, get_db
from backend.app.main import app
from backend.app.models.models import (
    Appointment, Branch, Clinic, Doctor, PatientLead, RevenueRecord, Service,
    User, VisitPhoto, VisitRecord,
)

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                       poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db(tmp_path, monkeypatch):
    from backend.app.api.endpoints import visits
    monkeypatch.setattr(visits.settings, "UPLOAD_DIR", str(tmp_path / "uploads"),
                        raising=False)
    Base.metadata.create_all(bind=engine)
    s = TestingSessionLocal()
    yield s
    s.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def setup(db):
    clinic = Clinic(name="CareDesk", is_active=True)
    db.add(clinic)
    db.flush()
    branch = Branch(clinic_id=clinic.id, name="CS1", address="1 A", is_active=True)
    service = Service(clinic_id=clinic.id, name="Tri mun", price=500000, duration_minutes=30)
    doctor = Doctor(clinic_id=clinic.id, name="BS An", is_active=True)
    staff = User(clinic_id=clinic.id, email="letan@x.vn", password_hash="x",
                 full_name="Le tan", role="receptionist", is_active=True)
    db.add_all([branch, service, doctor, staff])
    db.flush()
    patient = PatientLead(clinic_id=clinic.id, full_name="Nguyen Van A",
                          phone="0900000001", consent_given=True)
    db.add(patient)
    db.flush()
    start = datetime.datetime.combine(datetime.date.today(), datetime.time(9, 0))
    appt = Appointment(clinic_id=clinic.id, branch_id=branch.id, service_id=service.id,
                       doctor_id=doctor.id, patient_id=patient.id, status="confirmed",
                       start_time=start, end_time=start + datetime.timedelta(minutes=30))
    db.add(appt)
    db.commit()
    return {"clinic": clinic, "appt": appt, "patient": patient, "staff": staff,
            "branch": branch, "service": service, "doctor": doctor}


@pytest.fixture
def client(db, setup):
    from backend.app.api.deps import verify_receptionist_or_above
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[verify_receptionist_or_above] = lambda: setup["staff"]
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


API = "/api/v1/visits"


# --- queue -------------------------------------------------------------------

def test_the_queue_lists_todays_patients_in_time_order(client, setup):
    rows = client.get(f"{API}/queue").json()
    assert len(rows) == 1
    assert rows[0]["patient_name"] == "Nguyen Van A"
    assert rows[0]["queue_state"] == "waiting"


def test_marking_arrival_moves_the_patient_along(client, setup, db):
    res = client.post(f"{API}/queue/{setup['appt'].id}/arrive")
    assert res.json()["queue_state"] == "arrived"

    db.refresh(setup["appt"])
    assert setup["appt"].arrived_at is not None


def test_arriving_confirms_a_pending_appointment(client, setup, db):
    """Standing at the desk is the strongest confirmation there is."""
    setup["appt"].status = "pending"
    db.commit()

    client.post(f"{API}/queue/{setup['appt'].id}/arrive")
    db.refresh(setup["appt"])
    assert setup["appt"].status == "confirmed"


def test_the_queue_shows_how_long_someone_has_been_waiting(client, setup, db):
    setup["appt"].arrived_at = datetime.datetime.now() - datetime.timedelta(minutes=25)
    db.commit()

    row = client.get(f"{API}/queue").json()[0]
    assert row["queue_state"] == "arrived"
    assert 24 <= row["waited_minutes"] <= 26


def test_starting_a_walk_in_records_arrival_too(client, setup, db):
    """Staff who skip check-in must not leave a visit with no arrival time."""
    client.post(f"{API}/queue/{setup['appt'].id}/start")
    db.refresh(setup["appt"])
    assert setup["appt"].arrived_at is not None
    assert setup["appt"].started_at is not None


def test_a_finished_appointment_cannot_re_enter_the_queue(client, setup, db):
    setup["appt"].status = "cancelled"
    db.commit()
    assert client.post(f"{API}/queue/{setup['appt'].id}/arrive").status_code == 409


def test_queue_state_is_derived_not_a_new_status(client, setup, db):
    """Appointment.status still governs slot occupancy, revenue and reminders;
    the queue must not add values to it."""
    client.post(f"{API}/queue/{setup['appt'].id}/start")
    db.refresh(setup["appt"])
    assert setup["appt"].status == "confirmed"
    assert client.get(f"{API}/queue").json()[0]["queue_state"] == "in_progress"


# --- visit record -------------------------------------------------------------

def test_saving_a_record_also_closes_the_visit(client, setup, db):
    """Asking staff to save notes AND separately tick "completed" means half the
    visits never get ticked — and an unticked visit never counts towards
    retention or fires the follow-up chain."""
    res = client.put(f"{API}/records/{setup['appt'].id}", json={
        "chief_complaint": "Mun viem 2 thang",
        "treatment_done": "Lay nhan mun + chieu LED",
        "advice": "Tranh nang, rua mat 2 lan/ngay",
        "next_visit_days": 21,
    })
    assert res.status_code == 200

    db.refresh(setup["appt"])
    assert setup["appt"].status == "completed"
    assert db.query(VisitRecord).count() == 1


def test_closing_the_visit_books_the_revenue(client, setup, db):
    client.put(f"{API}/records/{setup['appt'].id}", json={"findings": "OK"})
    assert db.query(RevenueRecord).count() == 1


def test_saving_twice_updates_one_record(client, setup, db):
    """Two records for one visit would be two different accounts of what was done."""
    client.put(f"{API}/records/{setup['appt'].id}", json={"findings": "Lan 1"})
    client.put(f"{API}/records/{setup['appt'].id}", json={"findings": "Lan 2 da sua"})

    assert db.query(VisitRecord).count() == 1
    assert db.query(VisitRecord).first().findings == "Lan 2 da sua"


def test_the_record_is_readable_back(client, setup):
    client.put(f"{API}/records/{setup['appt'].id}", json={"advice": "Uong nhieu nuoc"})
    got = client.get(f"{API}/records/{setup['appt'].id}").json()
    assert got["advice"] == "Uong nhieu nuoc"
    assert got["patient_name"] == "Nguyen Van A"


def test_no_record_yet_is_not_an_error(client, setup):
    assert client.get(f"{API}/records/{setup['appt'].id}").json() is None


def test_patient_history_answers_what_did_we_do_last_time(client, setup, db):
    client.put(f"{API}/records/{setup['appt'].id}", json={"treatment_done": "Buoi 1"})

    older = datetime.datetime.now() - datetime.timedelta(days=30)
    a2 = Appointment(clinic_id=setup["clinic"].id, branch_id=setup["branch"].id,
                     service_id=setup["service"].id, doctor_id=setup["doctor"].id,
                     patient_id=setup["patient"].id, status="confirmed",
                     start_time=older, end_time=older + datetime.timedelta(minutes=30))
    db.add(a2)
    db.commit()
    client.put(f"{API}/records/{a2.id}", json={"treatment_done": "Buoi 2"})

    history = client.get(f"{API}/patients/{setup['patient'].id}/history").json()
    assert len(history) == 2
    assert {h["treatment_done"] for h in history} == {"Buoi 1", "Buoi 2"}


def test_an_absurd_recall_interval_is_refused(client, setup):
    res = client.put(f"{API}/records/{setup['appt'].id}", json={"next_visit_days": 99999})
    assert res.status_code == 422


# --- photos: patient data, treated as such -----------------------------------

def _png() -> bytes:
    # Smallest valid PNG; content does not matter, the handling does.
    return (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
            b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


def _upload(client, appt_id, kind="before", name="anh.png", ctype="image/png"):
    return client.post(f"{API}/records/{appt_id}/photos", params={"kind": kind},
                       files={"file": (name, io.BytesIO(_png()), ctype)})


def test_a_photo_uploads_and_is_served_back(client, setup, db):
    res = _upload(client, setup["appt"].id)
    assert res.status_code == 200
    photo = res.json()
    assert photo["kind"] == "before"

    served = client.get(photo["url"])
    assert served.status_code == 200
    assert served.content == _png()


def test_the_stored_filename_is_not_guessable(client, setup, db):
    """These are photographs of patients' faces. A path derived from a patient id
    or a counter lets anyone who finds one walk the rest."""
    _upload(client, setup["appt"].id, name="benh-nhan-nguyen-van-a.png")

    photo = db.query(VisitPhoto).first()
    assert "nguyen" not in photo.stored_name.lower()
    assert str(setup["patient"].id) != photo.stored_name.split(".")[0]
    assert len(photo.stored_name.split(".")[0]) >= 32
    assert photo.original_name == "benh-nhan-nguyen-van-a.png"


def test_a_photo_from_another_clinic_is_not_served(client, setup, db):
    """404, not 403: telling a caller the id exists is itself a leak."""
    other = Clinic(name="Khac", is_active=True)
    db.add(other)
    db.flush()
    record = VisitRecord(clinic_id=other.id, appointment_id=9999,
                         patient_id=setup["patient"].id)
    db.add(record)
    db.flush()
    stolen = VisitPhoto(clinic_id=other.id, visit_record_id=record.id, kind="after",
                        stored_name="deadbeef.png", content_type="image/png")
    db.add(stolen)
    db.commit()

    assert client.get(f"{API}/photos/{stolen.id}").status_code == 404


def test_photos_are_never_publicly_cacheable(client, setup):
    url = _upload(client, setup["appt"].id).json()["url"]
    assert "private" in client.get(url).headers.get("cache-control", "")


def test_a_non_image_upload_is_refused(client, setup, db):
    """An open-ended allowlist is how a photo feature becomes a file host."""
    res = client.post(f"{API}/records/{setup['appt'].id}/photos",
                      files={"file": ("evil.html", io.BytesIO(b"<script>"), "text/html")})
    assert res.status_code == 400
    assert db.query(VisitPhoto).count() == 0


def test_an_invalid_kind_is_refused(client, setup):
    assert _upload(client, setup["appt"].id, kind="sideways").status_code == 400


def test_uploading_a_photo_creates_the_record_if_needed(client, setup, db):
    """Staff often photograph before writing anything down."""
    _upload(client, setup["appt"].id)
    assert db.query(VisitRecord).count() == 1


def test_before_photos_are_listed_first(client, setup):
    _upload(client, setup["appt"].id, kind="after")
    _upload(client, setup["appt"].id, kind="before")

    photos = client.get(f"{API}/records/{setup['appt'].id}").json()["photos"]
    assert [p["kind"] for p in photos] == ["before", "after"]


def test_deleting_a_photo_removes_the_file_too(client, setup, db):
    from pathlib import Path
    from backend.app.api.endpoints import visits

    url = _upload(client, setup["appt"].id).json()["url"]
    stored = db.query(VisitPhoto).first().stored_name
    path = Path(visits.settings.UPLOAD_DIR) / stored
    assert path.exists()

    photo_id = url.rsplit("/", 1)[-1]
    assert client.delete(f"{API}/photos/{photo_id}").status_code == 204
    assert not path.exists(), "để lại ảnh bệnh nhân trên đĩa sau khi xoá là rò rỉ dữ liệu"
