"""Editable site copy, and permission to publish patient material.

The copy half is ordinary CRUD. The publishing half is not: before/after photos
and written reviews are patient data, and a clinical photograph drifting onto a
public page because someone mistook one checkbox for another is the kind of
mistake that ends a clinic's trust in the product — and possibly worse.

So the rule these tests exist to pin down is: a photo is public only when the
patient consented AND the clinic published, and withdrawing consent takes it
down without anyone having to remember a second switch.
"""
import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.api.endpoints.content import (
    PhotoConsentIn, PublishPhotoIn, PublishReviewIn, ContentUpdate,
    get_site_content, list_photos, publish_photo, publish_review,
    set_photo_consent, update_site_content,
)
from backend.app.core.database import Base
from backend.app.models.models import (
    Appointment, Branch, Clinic, Doctor, PatientLead, ReviewRequest, Service,
    SiteContent, User, VisitPhoto, VisitRecord,
)
from backend.app.services import site_content
from backend.app.services.landing import _load_cases, _load_reviews

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
    clinic = Clinic(name="CareDesk", is_active=True)
    db.add(clinic)
    db.flush()
    owner = User(clinic_id=clinic.id, email="o@x.vn", password_hash="x",
                 full_name="Chu", role="owner", is_active=True)
    branch = Branch(clinic_id=clinic.id, name="CS1", address="1 A", is_active=True)
    service = Service(clinic_id=clinic.id, name="Tri nam", price=900000, duration_minutes=60)
    doctor = Doctor(clinic_id=clinic.id, name="BS A", is_active=True)
    patient = PatientLead(clinic_id=clinic.id, full_name="Nguyen Thi Hoa", consent_given=True)
    db.add_all([owner, branch, service, doctor, patient])
    db.flush()
    start = datetime.datetime.now()
    appt = Appointment(clinic_id=clinic.id, branch_id=branch.id, service_id=service.id,
                       doctor_id=doctor.id, patient_id=patient.id, status="completed",
                       start_time=start, end_time=start + datetime.timedelta(minutes=60))
    db.add(appt)
    db.flush()
    record = VisitRecord(clinic_id=clinic.id, appointment_id=appt.id,
                         patient_id=patient.id, doctor_id=doctor.id)
    db.add(record)
    db.flush()
    before = VisitPhoto(clinic_id=clinic.id, visit_record_id=record.id, kind="before",
                        stored_name="b.png", content_type="image/png",
                        showcase_group="ca-1")
    after = VisitPhoto(clinic_id=clinic.id, visit_record_id=record.id, kind="after",
                       stored_name="a.png", content_type="image/png",
                       showcase_group="ca-1")
    review = ReviewRequest(clinic_id=clinic.id, patient_id=patient.id,
                           appointment_id=appt.id, status="answered", rating=5,
                           feedback="Da minh sang hon han sau 3 buoi.",
                           answered_at=datetime.datetime.now())
    db.add_all([before, after, review])
    db.commit()
    return {"clinic": clinic, "owner": owner, "before": before, "after": after,
            "review": review, "patient": patient}


# --- copy ---------------------------------------------------------------------

def test_a_clinic_that_has_edited_nothing_still_has_a_full_page(db, setup):
    """Defaults are real Vietnamese copy, not blanks — a clinic signed up for
    bookings, not to write a website before it can launch."""
    values = site_content.load(db, setup["clinic"].id)

    assert set(values) == set(site_content.defaults())
    assert values["hero_title"]
    assert "khoa học" in values["hero_title"]
    assert len(values["journey"]) == 3


def test_an_edit_overrides_only_that_key(db, setup):
    site_content.save(db, setup["clinic"].id, "hero_title", "Làn da của bạn, khoẻ từ gốc")
    db.commit()

    values = site_content.load(db, setup["clinic"].id)
    assert values["hero_title"] == "Làn da của bạn, khoẻ từ gốc"
    assert values["hero_subtitle"] == site_content.defaults()["hero_subtitle"]


def test_clearing_a_field_falls_back_to_the_default(db, setup):
    """An empty box should not produce an empty section on a live website."""
    site_content.save(db, setup["clinic"].id, "hero_title", "")
    db.commit()
    assert site_content.load(db, setup["clinic"].id)["hero_title"] == \
        site_content.defaults()["hero_title"]


def test_an_unknown_key_is_refused(db, setup):
    with pytest.raises(ValueError):
        site_content.save(db, setup["clinic"].id, "khong_ton_tai", "x")

    with pytest.raises(HTTPException) as exc:
        update_site_content(ContentUpdate(values={"khong_ton_tai": "x"}),
                            db=db, current_user=setup["owner"])
    assert exc.value.status_code == 400


def test_saving_twice_updates_one_row(db, setup):
    for text in ("Lần 1", "Lần 2"):
        site_content.save(db, setup["clinic"].id, "hero_title", text)
    db.commit()
    assert db.query(SiteContent).filter(SiteContent.key == "hero_title").count() == 1


def test_the_editor_gets_labels_and_defaults(db, setup):
    payload = get_site_content(db=db, current_user=setup["owner"])
    fields = {f["key"]: f for f in payload["schema"]}
    assert fields["stats"]["kind"] == "stats"
    assert fields["hero_title"]["default"]
    assert fields["stats"]["hint"], "trường dễ bị điền sai phải có ghi chú"


# --- publishing patient photos ------------------------------------------------

def test_a_photo_without_consent_cannot_be_published(db, setup):
    """The check the whole design exists for."""
    with pytest.raises(HTTPException) as exc:
        publish_photo(setup["before"].id, PublishPhotoIn(is_published=True),
                      db=db, current_user=setup["owner"])

    assert exc.value.status_code == 409
    assert "đồng ý" in exc.value.detail
    db.refresh(setup["before"])
    assert setup["before"].is_published is False


def test_consent_then_publish_is_the_only_route_out(db, setup):
    set_photo_consent(setup["before"].id, PhotoConsentIn(consent_given=True, note="ký giấy 12/08"),
                      db=db, current_user=setup["owner"])
    publish_photo(setup["before"].id, PublishPhotoIn(is_published=True),
                  db=db, current_user=setup["owner"])

    db.refresh(setup["before"])
    assert setup["before"].is_publicly_visible is True
    assert setup["before"].consent_by == setup["owner"].id
    assert setup["before"].consent_note == "ký giấy 12/08"


def test_withdrawing_consent_takes_the_photo_down_immediately(db, setup):
    """A patient who changes their mind must not depend on someone remembering
    to flip a second switch."""
    photo = setup["before"]
    set_photo_consent(photo.id, PhotoConsentIn(consent_given=True), db=db, current_user=setup["owner"])
    publish_photo(photo.id, PublishPhotoIn(is_published=True), db=db, current_user=setup["owner"])
    db.refresh(photo)
    assert photo.is_publicly_visible is True

    set_photo_consent(photo.id, PhotoConsentIn(consent_given=False), db=db, current_user=setup["owner"])
    db.refresh(photo)
    assert photo.consent_given_at is None
    assert photo.is_published is False, "gỡ đồng ý phải gỡ luôn khỏi trang"
    assert photo.is_publicly_visible is False


def test_the_public_page_shows_only_consented_and_published_photos(db, setup):
    """The landing query is the enforcement point — nothing downstream re-checks."""
    clinic_ids = [setup["clinic"].id]
    assert _load_cases(db, clinic_ids) == []

    # published but never consented: must stay invisible even if a flag slipped
    setup["before"].is_published = True
    db.commit()
    assert _load_cases(db, clinic_ids) == []

    # consented but not published
    setup["before"].is_published = False
    setup["before"].consent_given_at = datetime.datetime.now()
    db.commit()
    assert _load_cases(db, clinic_ids) == []

    # both
    setup["before"].is_published = True
    db.commit()
    assert len(_load_cases(db, clinic_ids)) == 1


def test_a_before_and_after_pair_becomes_one_case(db, setup):
    for photo in (setup["before"], setup["after"]):
        photo.consent_given_at = datetime.datetime.now()
        photo.is_published = True
    setup["after"].public_title = "Trị nám sau 3 buổi"
    db.commit()

    cases = _load_cases(db, [setup["clinic"].id])
    assert len(cases) == 1
    assert cases[0].before_url and cases[0].after_url
    assert cases[0].title == "Trị nám sau 3 buổi"


def test_the_public_case_never_carries_the_patient_name(db, setup):
    """The page shows a result, not a person."""
    for photo in (setup["before"], setup["after"]):
        photo.consent_given_at = datetime.datetime.now()
        photo.is_published = True
    db.commit()

    case = _load_cases(db, [setup["clinic"].id])[0]
    assert "Hoa" not in (case.title or "")
    assert not hasattr(case, "patient_name")


def test_staff_see_the_patient_name_but_the_photo_list_is_clinic_scoped(db, setup):
    rows = list_photos(db=db, current_user=setup["owner"])
    assert {r.patient_name for r in rows} == {"Nguyen Thi Hoa"}

    other = Clinic(name="Khac", is_active=True)
    db.add(other)
    db.flush()
    stranger = User(clinic_id=other.id, email="x@y.vn", password_hash="x",
                    full_name="Nguoi la", role="owner", is_active=True)
    db.add(stranger)
    db.commit()
    assert list_photos(db=db, current_user=stranger) == []


def test_another_clinic_cannot_publish_this_photo(db, setup):
    other = Clinic(name="Khac", is_active=True)
    db.add(other)
    db.flush()
    stranger = User(clinic_id=other.id, email="x@y.vn", password_hash="x",
                    full_name="Nguoi la", role="owner", is_active=True)
    db.add(stranger)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        set_photo_consent(setup["before"].id, PhotoConsentIn(consent_given=True),
                          db=db, current_user=stranger)
    assert exc.value.status_code == 404


# --- publishing reviews --------------------------------------------------------

def test_a_review_is_hidden_until_the_clinic_publishes_it(db, setup):
    assert _load_reviews(db, [setup["clinic"].id]) == []

    publish_review(setup["review"].id,
                   PublishReviewIn(is_published=True, public_name="Chị Hoa N."),
                   db=db, current_user=setup["owner"])

    reviews = _load_reviews(db, [setup["clinic"].id])
    assert len(reviews) == 1
    assert reviews[0].name == "Chị Hoa N."
    assert reviews[0].rating == 5


def test_the_public_name_is_entered_not_taken_from_the_record(db, setup):
    """The full name on file is personal data; a public credit is a choice."""
    publish_review(setup["review"].id, PublishReviewIn(is_published=True),
                   db=db, current_user=setup["owner"])

    shown = _load_reviews(db, [setup["clinic"].id])[0]
    assert shown.name == "Khách hàng"
    assert "Nguyen Thi Hoa" not in shown.name


def test_a_rating_with_no_words_cannot_be_published(db, setup):
    silent = ReviewRequest(clinic_id=setup["clinic"].id, patient_id=setup["patient"].id,
                           status="answered", rating=5)
    db.add(silent)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        publish_review(silent.id, PublishReviewIn(is_published=True),
                       db=db, current_user=setup["owner"])
    assert exc.value.status_code == 400


def test_unpublishing_a_review_removes_it_from_the_page(db, setup):
    publish_review(setup["review"].id, PublishReviewIn(is_published=True),
                   db=db, current_user=setup["owner"])
    assert len(_load_reviews(db, [setup["clinic"].id])) == 1

    publish_review(setup["review"].id, PublishReviewIn(is_published=False),
                   db=db, current_user=setup["owner"])
    assert _load_reviews(db, [setup["clinic"].id]) == []
