"""The 15-minute setup a clinic goes through before it can take a booking.

Two jobs, and the second is easy to underrate:

1. Collect the minimum the AI needs to be useful — hours, services with prices,
   a doctor with a working schedule. A clinic dropped straight into an empty
   dashboard has to find five separate screens before it can try a single chat,
   and most never do.

2. Record what the clinic's numbers looked like *before*. We sell "more bookings
   and fewer no-shows"; both are comparisons. Ask on day sixty and nobody
   remembers, so there is no way to show what the money bought.
"""
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.api.deps import verify_owner
from backend.app.core.database import get_db
from backend.app.models.models import Branch, Clinic, Doctor, Service, User, WorkingSchedule
from backend.app.services.audit import log_action

router = APIRouter()


class BaselineIn(BaseModel):
    """The clinic's own estimate of where they are starting from."""
    monthly_bookings: Optional[int] = Field(None, ge=0, le=100000)
    no_show_percent: Optional[float] = Field(None, ge=0, le=100)
    daily_price_asks: Optional[int] = Field(None, ge=0, le=10000)
    # The North Star. Asked now because it is the one number nobody can
    # reconstruct later, and the whole retention claim rests on having a "before".
    return_percent: Optional[float] = Field(None, ge=0, le=100)


def _clinic(db: Session, user: User) -> Clinic:
    clinic = db.query(Clinic).filter(Clinic.id == user.clinic_id).first()
    if not clinic:
        raise HTTPException(status_code=404, detail="Tài khoản chưa gắn với phòng khám nào.")
    return clinic


def _steps(db: Session, clinic: Clinic) -> list[dict]:
    """Progress for the wizard. Derived from real data rather than a stored
    step counter, so a clinic that fills something in from another screen — or
    deletes their only doctor — sees the truth either way."""
    cid = clinic.id
    has_branch = db.query(Branch).filter(Branch.clinic_id == cid).first() is not None
    has_hours = db.query(Branch).filter(
        Branch.clinic_id == cid, Branch.working_hours != None,   # noqa: E711
        Branch.working_hours != "",
    ).first() is not None
    has_service = db.query(Service).filter(Service.clinic_id == cid).first() is not None
    has_doctor = db.query(Doctor).filter(
        Doctor.clinic_id == cid, Doctor.is_active == True        # noqa: E712
    ).first() is not None
    has_schedule = db.query(WorkingSchedule).join(
        Doctor, WorkingSchedule.doctor_id == Doctor.id
    ).filter(Doctor.clinic_id == cid).first() is not None

    return [
        {"key": "clinic", "title": "Thông tin phòng khám", "path": "/clinic",
         "done": bool(clinic.name and clinic.address and clinic.phone),
         "hint": "Tên, địa chỉ và số điện thoại — AI cần để trả lời khách hỏi ở đâu."},
        {"key": "hours", "title": "Giờ mở cửa", "path": "/clinic",
         "done": has_branch and has_hours,
         "hint": "Cơ sở và giờ làm việc."},
        {"key": "services", "title": "Dịch vụ và giá", "path": "/services",
         "done": has_service,
         "hint": "3–5 dịch vụ chính. Đây là thứ phần lớn khách hỏi đầu tiên."},
        {"key": "doctors", "title": "Bác sĩ và lịch làm việc", "path": "/doctors",
         "done": has_doctor and has_schedule,
         "hint": "Không có lịch làm việc thì AI không chốt được lịch hẹn nào."},
        {"key": "baseline", "title": "Số liệu hiện tại", "path": "/onboarding",
         "done": clinic.baseline_captured_at is not None,
         "hint": "Để 2–3 tháng nữa đo được CareDesk mang lại thay đổi gì — "
                 "nhất là tỷ lệ khách quay lại."},
    ]


@router.get("/status")
def onboarding_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner),
) -> Any:
    clinic = _clinic(db, current_user)
    steps = _steps(db, clinic)
    # Step 5 is a question, not a configuration: a clinic that skips it can still
    # operate, so it does not gate going live.
    blocking = [s for s in steps if s["key"] != "baseline"]
    return {
        "steps": steps,
        "completed_at": clinic.onboarding_completed_at,
        "can_go_live": all(s["done"] for s in blocking),
        "next": next((s["key"] for s in steps if not s["done"]), None),
    }


@router.put("/baseline")
def save_baseline(
    body: BaselineIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner),
) -> Any:
    clinic = _clinic(db, current_user)
    clinic.baseline_monthly_bookings = body.monthly_bookings
    clinic.baseline_no_show_percent = body.no_show_percent
    clinic.baseline_daily_price_asks = body.daily_price_asks
    clinic.baseline_return_percent = body.return_percent
    clinic.baseline_captured_at = datetime.now()
    log_action(db, current_user.id, "save_baseline",
               f"Mốc so sánh: {body.monthly_bookings} lịch/tháng, "
               f"{body.no_show_percent}% không đến")
    db.commit()
    return {"saved": True, "captured_at": clinic.baseline_captured_at}


@router.post("/complete")
def complete_onboarding(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner),
) -> Any:
    """Finish setup and open the public link.

    Refuses while a blocking step is unfinished. Publishing a landing page for a
    clinic with no working schedule means real patients arrive and are told
    "hiện chưa có khung giờ trống" — the worst possible first impression, and one
    the clinic will blame on the AI.
    """
    clinic = _clinic(db, current_user)
    missing = [s for s in _steps(db, clinic) if not s["done"] and s["key"] != "baseline"]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Chưa thể mở link công khai. Còn thiếu: "
                   + ", ".join(s["title"] for s in missing),
        )

    clinic.onboarding_completed_at = datetime.now()
    clinic.landing_enabled = True
    log_action(db, current_user.id, "complete_onboarding", "Hoàn tất thiết lập, mở link công khai")
    db.commit()
    return {"completed_at": clinic.onboarding_completed_at, "slug": clinic.slug}
