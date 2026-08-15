"""Today's queue, and the record of what happened at each visit.

The queue is the screen a receptionist opens every morning. That matters more
than its feature list: the clearest signal a pilot is working is whether staff
open the product without being told, and nothing else in CareDesk earns a daily
open the way "who is here right now" does.

Visit records are deliberately light — see models.VisitRecord. No prescriptions.
Photos are the part that carries weight for dermatology and aesthetics, and they
are patient photographs, so they are stored under unguessable names and served
only through the authenticated endpoint below.
"""
import logging
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.api.deps import verify_receptionist_or_above
from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.models.models import (
    Appointment, Doctor, PatientLead, User, VisitPhoto, VisitRecord,
)
from backend.app.services.audit import log_action
from backend.app.services.events import emit_event
from backend.app.core import clock

logger = logging.getLogger(__name__)

router = APIRouter()

# Only formats a phone camera actually produces. An open-ended allowlist here is
# how an "image upload" becomes an arbitrary file host.
ALLOWED_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_PHOTO_BYTES = 8 * 1024 * 1024


def _upload_dir() -> Path:
    d = Path(settings.UPLOAD_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- Queue -------------------------------------------------------------------

class QueueEntry(BaseModel):
    appointment_id: int
    patient_id: int
    patient_name: str
    patient_phone: Optional[str] = None
    service_name: Optional[str] = None
    doctor_name: Optional[str] = None
    branch_name: Optional[str] = None
    start_time: datetime
    status: str
    # waiting | arrived | in_progress | done | no_show | cancelled
    queue_state: str
    waited_minutes: Optional[int] = None
    has_record: bool = False


def _queue_state(appt: Appointment) -> str:
    """Derived, not stored. Keeps the queue out of Appointment.status, which
    already governs slot occupancy, revenue and reminders."""
    if appt.status in ("cancelled", "no_show"):
        return appt.status
    if appt.status == "completed":
        return "done"
    if appt.started_at:
        return "in_progress"
    if appt.arrived_at:
        return "arrived"
    return "waiting"


@router.get("/queue", response_model=List[QueueEntry])
def todays_queue(
    day: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above),
) -> Any:
    """Everyone expected today, in the order they are due."""
    target = datetime.fromisoformat(day).date() if day else clock.now().date()
    start = datetime.combine(target, datetime.min.time())
    end = start + timedelta(days=1)

    query = db.query(Appointment).filter(
        Appointment.start_time >= start, Appointment.start_time < end)
    if current_user.clinic_id:
        query = query.filter(Appointment.clinic_id == current_user.clinic_id)

    now = clock.now()
    out = []
    for appt in query.order_by(Appointment.start_time).all():
        waited = None
        if appt.arrived_at and not appt.started_at:
            # How long this patient has been sitting in the waiting room. The
            # single most useful number on the screen.
            waited = max(0, int((now - appt.arrived_at.replace(tzinfo=None)).total_seconds() // 60))
        out.append(QueueEntry(
            appointment_id=appt.id,
            patient_id=appt.patient_id,
            patient_name=appt.patient.full_name if appt.patient else "—",
            patient_phone=appt.patient.phone if appt.patient else None,
            service_name=appt.service.name if appt.service else None,
            doctor_name=appt.doctor.name if appt.doctor else None,
            branch_name=appt.branch.name if appt.branch else None,
            start_time=appt.start_time,
            status=appt.status,
            queue_state=_queue_state(appt),
            waited_minutes=waited,
            has_record=appt.id in _records_for(db, [appt.id]),
        ))
    return out


def _records_for(db: Session, appointment_ids: List[int]) -> set:
    if not appointment_ids:
        return set()
    rows = db.query(VisitRecord.appointment_id).filter(
        VisitRecord.appointment_id.in_(appointment_ids)).all()
    return {r[0] for r in rows}


def _get_appointment(db: Session, appt_id: int, user: User) -> Appointment:
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Không tìm thấy lịch hẹn.")
    if user.clinic_id and appt.clinic_id != user.clinic_id:
        raise HTTPException(status_code=403, detail="Lịch hẹn không thuộc phòng khám của bạn.")
    return appt


@router.post("/queue/{appt_id}/arrive")
def mark_arrived(appt_id: int, db: Session = Depends(get_db),
                 current_user: User = Depends(verify_receptionist_or_above)) -> Any:
    appt = _get_appointment(db, appt_id, current_user)
    if appt.status in ("cancelled", "completed", "no_show"):
        raise HTTPException(status_code=409, detail="Lịch hẹn này đã kết thúc.")
    appt.arrived_at = appt.arrived_at or clock.now()
    # Arriving is the strongest possible confirmation: they are standing here.
    if appt.status == "pending":
        appt.status = "confirmed"
    log_action(db, current_user.id, "queue_arrive", f"Khách đến — lịch hẹn #{appt.id}")
    db.commit()
    return {"appointment_id": appt.id, "queue_state": _queue_state(appt)}


@router.post("/queue/{appt_id}/start")
def mark_started(appt_id: int, db: Session = Depends(get_db),
                 current_user: User = Depends(verify_receptionist_or_above)) -> Any:
    appt = _get_appointment(db, appt_id, current_user)
    if appt.status in ("cancelled", "completed", "no_show"):
        raise HTTPException(status_code=409, detail="Lịch hẹn này đã kết thúc.")
    now = clock.now()
    appt.arrived_at = appt.arrived_at or now   # walk-in: started without checking in
    appt.started_at = appt.started_at or now
    log_action(db, current_user.id, "queue_start", f"Bắt đầu khám — lịch hẹn #{appt.id}")
    db.commit()
    return {"appointment_id": appt.id, "queue_state": _queue_state(appt)}


# --- Visit record ------------------------------------------------------------

class VisitRecordIn(BaseModel):
    chief_complaint: Optional[str] = None
    findings: Optional[str] = None
    treatment_done: Optional[str] = None
    advice: Optional[str] = None
    # The doctor's own recall interval. A laser course and a routine check are
    # not the same appointment, so this beats the fixed 30-day automation.
    next_visit_days: Optional[int] = Field(None, ge=0, le=1095)


class VisitPhotoOut(BaseModel):
    id: int
    kind: str
    caption: Optional[str] = None
    url: str
    created_at: datetime


class VisitRecordOut(VisitRecordIn):
    id: int
    appointment_id: int
    patient_id: int
    patient_name: Optional[str] = None
    doctor_name: Optional[str] = None
    visit_date: Optional[datetime] = None
    photos: List[VisitPhotoOut] = []
    created_at: datetime


def _to_out(record: VisitRecord) -> VisitRecordOut:
    return VisitRecordOut(
        id=record.id, appointment_id=record.appointment_id,
        patient_id=record.patient_id,
        patient_name=record.patient.full_name if record.patient else None,
        doctor_name=record.doctor.name if record.doctor else None,
        visit_date=record.appointment.start_time if record.appointment else None,
        chief_complaint=record.chief_complaint, findings=record.findings,
        treatment_done=record.treatment_done, advice=record.advice,
        next_visit_days=record.next_visit_days,
        created_at=record.created_at,
        photos=[
            VisitPhotoOut(id=p.id, kind=p.kind, caption=p.caption,
                          url=f"{settings.API_V1_STR}/visits/photos/{p.id}",
                          created_at=p.created_at)
            for p in sorted(record.photos, key=lambda x: (x.kind != "before", x.id))
        ],
    )


@router.get("/records/{appt_id}", response_model=Optional[VisitRecordOut])
def get_visit_record(appt_id: int, db: Session = Depends(get_db),
                     current_user: User = Depends(verify_receptionist_or_above)) -> Any:
    _get_appointment(db, appt_id, current_user)
    record = db.query(VisitRecord).filter(VisitRecord.appointment_id == appt_id).first()
    return _to_out(record) if record else None


@router.put("/records/{appt_id}", response_model=VisitRecordOut)
def save_visit_record(appt_id: int, body: VisitRecordIn,
                      db: Session = Depends(get_db),
                      current_user: User = Depends(verify_receptionist_or_above)) -> Any:
    """Create or update the record for one visit, and close the visit.

    Saving a record is what "khám xong" means in practice, so it completes the
    appointment — which is also what makes the visit count towards the retention
    cohort and fires the follow-up automations. Asking staff to save the notes
    *and* separately mark it complete means half the visits never get marked.
    """
    appt = _get_appointment(db, appt_id, current_user)
    record = db.query(VisitRecord).filter(VisitRecord.appointment_id == appt_id).first()

    if record is None:
        record = VisitRecord(
            clinic_id=appt.clinic_id, appointment_id=appt.id,
            patient_id=appt.patient_id, doctor_id=appt.doctor_id,
            created_by=current_user.id,
        )
        db.add(record)

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(record, field, value)

    newly_completed = appt.status != "completed"
    if newly_completed:
        from backend.app.api.endpoints.appointment import handle_status_transition
        old = appt.status
        appt.status = "completed"
        appt.started_at = appt.started_at or clock.now()
        # Revenue, review request and the recall chain all hang off this.
        handle_status_transition(db, appt, old)

    if body.next_visit_days:
        # Let the automation engine prefer the doctor's interval over its default.
        emit_event(db, appt.clinic_id, "recall_interval_set",
                   patient_id=appt.patient_id,
                   payload={"appointment_id": appt.id, "days": body.next_visit_days})

    log_action(db, current_user.id, "save_visit_record",
               f"Hồ sơ khám cho lịch hẹn #{appt.id}")
    db.commit()
    db.refresh(record)
    return _to_out(record)


@router.get("/patients/{patient_id}/history", response_model=List[VisitRecordOut])
def patient_history(patient_id: int, db: Session = Depends(get_db),
                    current_user: User = Depends(verify_receptionist_or_above)) -> Any:
    """Every visit for one patient, newest first — "what did we do last time"."""
    patient = db.query(PatientLead).filter(PatientLead.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách hàng.")
    if current_user.clinic_id and patient.clinic_id != current_user.clinic_id:
        raise HTTPException(status_code=403, detail="Khách hàng không thuộc phòng khám của bạn.")

    records = db.query(VisitRecord).filter(
        VisitRecord.patient_id == patient_id
    ).order_by(VisitRecord.created_at.desc()).all()
    return [_to_out(r) for r in records]


# --- Photos ------------------------------------------------------------------

@router.post("/records/{appt_id}/photos", response_model=VisitPhotoOut)
async def upload_photo(appt_id: int, kind: str = "after", caption: str = "",
                       file: UploadFile = File(...),
                       db: Session = Depends(get_db),
                       current_user: User = Depends(verify_receptionist_or_above)) -> Any:
    if kind not in ("before", "after"):
        raise HTTPException(status_code=400, detail="kind phải là 'before' hoặc 'after'.")
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Chỉ nhận ảnh JPG, PNG hoặc WEBP.")

    appt = _get_appointment(db, appt_id, current_user)
    record = db.query(VisitRecord).filter(VisitRecord.appointment_id == appt_id).first()
    if record is None:
        record = VisitRecord(clinic_id=appt.clinic_id, appointment_id=appt.id,
                             patient_id=appt.patient_id, doctor_id=appt.doctor_id,
                             created_by=current_user.id)
        db.add(record)
        db.flush()

    data = await file.read()
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413,
                            detail=f"Ảnh quá lớn (tối đa {MAX_PHOTO_BYTES // 1024 // 1024}MB).")

    # token_hex, not the patient id or a counter: the filename must not let
    # anyone enumerate or guess another patient's photograph.
    stored = f"{secrets.token_hex(16)}{ALLOWED_IMAGE_TYPES[file.content_type]}"
    (_upload_dir() / stored).write_bytes(data)

    photo = VisitPhoto(
        clinic_id=appt.clinic_id, visit_record_id=record.id, kind=kind,
        stored_name=stored, original_name=file.filename,
        content_type=file.content_type, size_bytes=len(data),
        caption=caption or None, uploaded_by=current_user.id,
    )
    db.add(photo)
    log_action(db, current_user.id, "upload_visit_photo",
               f"Ảnh {kind} cho lịch hẹn #{appt.id}")
    db.commit()
    db.refresh(photo)
    return VisitPhotoOut(id=photo.id, kind=photo.kind, caption=photo.caption,
                         url=f"{settings.API_V1_STR}/visits/photos/{photo.id}",
                         created_at=photo.created_at)


@router.get("/photos/{photo_id}")
def get_photo(photo_id: int, db: Session = Depends(get_db),
              current_user: User = Depends(verify_receptionist_or_above)):
    """Serve a patient photo — authenticated and clinic-scoped, never static.

    A static mount would make every patient photograph readable by anyone with
    the URL, forever, with no way to revoke it. This costs one database lookup
    per image and is the difference between a photo feature and a data breach.
    """
    photo = db.query(VisitPhoto).filter(VisitPhoto.id == photo_id).first()
    if not photo:
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh.")
    if current_user.clinic_id and photo.clinic_id != current_user.clinic_id:
        # 404 rather than 403: confirming the id exists tells a caller from
        # another clinic that this photo is real.
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh.")

    path = _upload_dir() / photo.stored_name
    if not path.exists():
        logger.error("Ảnh #%s có trong DB nhưng thiếu file trên đĩa: %s", photo.id, path)
        raise HTTPException(status_code=410, detail="File ảnh không còn trên máy chủ.")
    return FileResponse(path, media_type=photo.content_type or "image/jpeg",
                        headers={"Cache-Control": "private, max-age=3600"})


@router.delete("/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_photo(photo_id: int, db: Session = Depends(get_db),
                 current_user: User = Depends(verify_receptionist_or_above)):
    photo = db.query(VisitPhoto).filter(VisitPhoto.id == photo_id).first()
    if not photo:
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh.")
    if current_user.clinic_id and photo.clinic_id != current_user.clinic_id:
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh.")

    (_upload_dir() / photo.stored_name).unlink(missing_ok=True)
    log_action(db, current_user.id, "delete_visit_photo", f"Xoá ảnh #{photo.id}")
    db.delete(photo)
    db.commit()
    return
