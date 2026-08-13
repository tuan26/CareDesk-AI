"""Managing what the public site shows.

Three things a clinic controls here: the copy, which before/after photos are
allowed out, and which reviews are shown.

The last two carry the weight. They are the elements that actually convert an
aesthetics visitor, and both already accumulate on their own — every visit is
photographed, every visit is followed by a rating request — so the clinic's job
is choosing, not producing. What choosing must never be is casual: these are
patient photographs and patient words.
"""
from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.api.deps import verify_owner, verify_receptionist_or_above
from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.models.models import (
    Appointment, PatientLead, ReviewRequest, User, VisitPhoto, VisitRecord,
)
from backend.app.services import site_content
from backend.app.services.audit import log_action

router = APIRouter()


# --- Copy --------------------------------------------------------------------

class ContentUpdate(BaseModel):
    values: dict


@router.get("/site")
def get_site_content(db: Session = Depends(get_db),
                     current_user: User = Depends(verify_receptionist_or_above)) -> Any:
    """Current copy plus the field definitions, so the editor can show each
    field's default and explain what it is for."""
    return {
        "values": site_content.load(db, current_user.clinic_id),
        "schema": site_content.schema(),
    }


@router.put("/site")
def update_site_content(body: ContentUpdate,
                        db: Session = Depends(get_db),
                        current_user: User = Depends(verify_owner)) -> Any:
    if not current_user.clinic_id:
        raise HTTPException(status_code=400, detail="Tài khoản chưa gắn phòng khám.")

    for key, value in body.values.items():
        try:
            site_content.save(db, current_user.clinic_id, key, value, current_user.id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    log_action(db, current_user.id, "update_site_content",
               f"Sửa nội dung trang: {', '.join(sorted(body.values))}")
    db.commit()
    return {"values": site_content.load(db, current_user.clinic_id)}


# --- Before / after ----------------------------------------------------------

class PhotoConsentIn(BaseModel):
    """Recording that a patient agreed their photo may be shown publicly."""
    consent_given: bool
    note: Optional[str] = Field(None, max_length=200)


class PublishPhotoIn(BaseModel):
    is_published: bool
    public_title: Optional[str] = Field(None, max_length=120)
    showcase_group: Optional[str] = Field(None, max_length=60)


class ShowcasePhotoOut(BaseModel):
    id: int
    kind: str
    url: str
    caption: Optional[str] = None
    public_title: Optional[str] = None
    showcase_group: Optional[str] = None
    patient_name: Optional[str] = None      # staff view only
    service_name: Optional[str] = None
    visit_date: Optional[datetime] = None
    has_consent: bool = False
    is_published: bool = False
    consent_note: Optional[str] = None


def _photo_out(db: Session, p: VisitPhoto, *, for_staff: bool) -> ShowcasePhotoOut:
    record = p.visit
    appt = record.appointment if record else None
    return ShowcasePhotoOut(
        id=p.id, kind=p.kind,
        url=f"{settings.API_V1_STR}/visits/photos/{p.id}",
        caption=p.caption, public_title=p.public_title,
        showcase_group=p.showcase_group,
        # Never leave the building: the public page shows a result, not a person.
        patient_name=(record.patient.full_name if for_staff and record and record.patient else None),
        service_name=appt.service.name if appt and appt.service else None,
        visit_date=appt.start_time if appt else None,
        has_consent=p.consent_given_at is not None,
        is_published=p.is_published,
        consent_note=p.consent_note if for_staff else None,
    )


def _get_photo(db: Session, photo_id: int, user: User) -> VisitPhoto:
    photo = db.query(VisitPhoto).filter(VisitPhoto.id == photo_id).first()
    if not photo:
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh.")
    if user.clinic_id and photo.clinic_id != user.clinic_id:
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh.")
    return photo


@router.get("/photos", response_model=List[ShowcasePhotoOut])
def list_photos(only_consented: bool = False,
                db: Session = Depends(get_db),
                current_user: User = Depends(verify_receptionist_or_above)) -> Any:
    """Every photo the clinic could publish, newest first."""
    query = db.query(VisitPhoto)
    if current_user.clinic_id:
        query = query.filter(VisitPhoto.clinic_id == current_user.clinic_id)
    if only_consented:
        query = query.filter(VisitPhoto.consent_given_at != None)  # noqa: E711
    rows = query.order_by(VisitPhoto.id.desc()).limit(300).all()
    return [_photo_out(db, p, for_staff=True) for p in rows]


@router.put("/photos/{photo_id}/consent", response_model=ShowcasePhotoOut)
def set_photo_consent(photo_id: int, body: PhotoConsentIn,
                      db: Session = Depends(get_db),
                      current_user: User = Depends(verify_owner)) -> Any:
    """Record — or withdraw — the patient's permission to be shown publicly.

    Withdrawing also unpublishes. A patient who changes their mind should not
    have to rely on someone remembering to flip a second switch, and "I asked
    you to take it down" is not a request that can be half-actioned.
    """
    photo = _get_photo(db, photo_id, current_user)

    if body.consent_given:
        photo.consent_given_at = datetime.now()
        photo.consent_by = current_user.id
        photo.consent_note = body.note
        action = "Ghi nhận đồng ý đăng ảnh"
    else:
        photo.consent_given_at = None
        photo.consent_by = None
        photo.consent_note = body.note
        photo.is_published = False
        action = "Thu hồi đồng ý — đã gỡ ảnh khỏi trang công khai"

    log_action(db, current_user.id, "photo_consent", f"{action} (ảnh #{photo.id})")
    db.commit()
    db.refresh(photo)
    return _photo_out(db, photo, for_staff=True)


@router.put("/photos/{photo_id}/publish", response_model=ShowcasePhotoOut)
def publish_photo(photo_id: int, body: PublishPhotoIn,
                  db: Session = Depends(get_db),
                  current_user: User = Depends(verify_owner)) -> Any:
    photo = _get_photo(db, photo_id, current_user)

    if body.is_published and photo.consent_given_at is None:
        # The check that makes the whole design mean something.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Chưa ghi nhận khách đồng ý cho đăng ảnh này. "
                   "Phải xác nhận đồng ý trước khi đăng lên trang công khai.")

    photo.is_published = body.is_published
    if body.public_title is not None:
        photo.public_title = body.public_title
    if body.showcase_group is not None:
        photo.showcase_group = body.showcase_group

    log_action(db, current_user.id, "publish_photo",
               f"{'Đăng' if body.is_published else 'Gỡ'} ảnh #{photo.id} trên trang công khai")
    db.commit()
    db.refresh(photo)
    return _photo_out(db, photo, for_staff=True)


# --- Reviews -----------------------------------------------------------------

class ReviewOut(BaseModel):
    id: int
    rating: Optional[int] = None
    feedback: Optional[str] = None
    patient_name: Optional[str] = None
    public_name: Optional[str] = None
    is_published: bool = False
    answered_at: Optional[datetime] = None


class PublishReviewIn(BaseModel):
    is_published: bool
    # Entered by staff rather than copied from the record: "Chị Ngọc A." is a
    # public credit, the full name on file is personal data.
    public_name: Optional[str] = Field(None, max_length=60)


@router.get("/reviews", response_model=List[ReviewOut])
def list_reviews(db: Session = Depends(get_db),
                 current_user: User = Depends(verify_receptionist_or_above)) -> Any:
    query = db.query(ReviewRequest).filter(ReviewRequest.rating != None)  # noqa: E711
    if current_user.clinic_id:
        query = query.filter(ReviewRequest.clinic_id == current_user.clinic_id)
    rows = query.order_by(ReviewRequest.answered_at.desc().nullslast()).limit(200).all()

    patients = {p.id: p.full_name for p in db.query(PatientLead).filter(
        PatientLead.id.in_([r.patient_id for r in rows] or [0])).all()}
    return [
        ReviewOut(id=r.id, rating=r.rating, feedback=r.feedback,
                  patient_name=patients.get(r.patient_id),
                  public_name=r.public_name, is_published=r.is_published,
                  answered_at=r.answered_at)
        for r in rows
    ]


@router.put("/reviews/{review_id}/publish", response_model=ReviewOut)
def publish_review(review_id: int, body: PublishReviewIn,
                   db: Session = Depends(get_db),
                   current_user: User = Depends(verify_owner)) -> Any:
    review = db.query(ReviewRequest).filter(ReviewRequest.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Không tìm thấy đánh giá.")
    if current_user.clinic_id and review.clinic_id != current_user.clinic_id:
        raise HTTPException(status_code=404, detail="Không tìm thấy đánh giá.")
    if body.is_published and not review.feedback:
        raise HTTPException(status_code=400,
                            detail="Đánh giá này chưa có nội dung để hiển thị.")

    review.is_published = body.is_published
    review.published_at = datetime.now() if body.is_published else None
    if body.public_name is not None:
        review.public_name = body.public_name

    log_action(db, current_user.id, "publish_review",
               f"{'Đăng' if body.is_published else 'Gỡ'} đánh giá #{review.id}")
    db.commit()
    db.refresh(review)
    return ReviewOut(id=review.id, rating=review.rating, feedback=review.feedback,
                     public_name=review.public_name, is_published=review.is_published,
                     answered_at=review.answered_at)
