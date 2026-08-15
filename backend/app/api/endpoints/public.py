"""
Public (no-login) endpoints reached from reminder messages:
tokenized one-click confirm / cancel links for patients.
"""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.models.models import (
    Appointment, Branch, Clinic, Organization, ReminderLog, WorkingSchedule,
)
from backend.app.schemas.schemas import PublicBranchOut, PublicClinicOut
from backend.app.services.reminder import verify_public_token
from backend.app.services.rate_limit import public_rate_limiter
from backend.app.services.audit import log_action
from backend.app.services.ws_manager import ws_manager
from backend.app.core import clock

router = APIRouter()


# ---------- Per-clinic / per-chain public link resolution (slug -> tenant) ----------

def _branch_view(db: Session, b: Branch) -> PublicBranchOut:
    """A location with no working schedule can be listed but not booked, so the
    picker can disable it instead of letting a patient walk into a conversation
    that can never produce a slot."""
    bookable = db.query(WorkingSchedule).filter(
        WorkingSchedule.branch_id == b.id).first() is not None
    return PublicBranchOut(
        id=b.id, slug=b.slug, name=b.name, address=b.address,
        phone=b.phone, working_hours=b.working_hours, bookable=bookable,
    )


def _active_branches(db: Session, clinic_id: int) -> list[PublicBranchOut]:
    rows = (
        db.query(Branch)
        .filter(Branch.clinic_id == clinic_id, Branch.is_active == True)  # noqa: E712
        .order_by(Branch.id)
        .all()
    )
    return [_branch_view(db, b) for b in rows]


@router.get("/clinic-by-slug/{slug}", response_model=PublicClinicOut,
            dependencies=[Depends(public_rate_limiter)])
def clinic_by_slug(slug: str, db: Session = Depends(get_db)):
    """Resolve a public clinic link /c/<slug> to the clinic the widget should talk to."""
    clinic = db.query(Clinic).filter(Clinic.slug == slug).first()
    if not clinic:
        raise HTTPException(status_code=404, detail="Không tìm thấy phòng khám.")
    return PublicClinicOut(
        clinic_id=clinic.id, slug=clinic.slug, name=clinic.name, logo_url=clinic.logo_url,
        address=clinic.address, phone=clinic.phone, is_active=bool(clinic.is_active),
        default_locale=clinic.default_locale or "vi",
        public_chat_v1_enabled=bool(clinic.public_chat_v1_enabled),
        # Legacy /c/<slug> links name no location, so the chat page still needs
        # the list to let the patient pick one.
        branches=_active_branches(db, clinic.id),
    )


@router.get("/org/{org_slug}/clinics/{clinic_slug}", response_model=PublicClinicOut,
            dependencies=[Depends(public_rate_limiter)])
def clinic_in_org(org_slug: str, clinic_slug: str, db: Session = Depends(get_db)):
    """Hierarchical resolve: the clinic MUST belong to the org named in the URL."""
    org = db.query(Organization).filter(Organization.slug == org_slug).first()
    if not org:
        raise HTTPException(status_code=404, detail="Không tìm thấy chuỗi phòng khám.")
    clinic = db.query(Clinic).filter(
        Clinic.slug == clinic_slug, Clinic.organization_id == org.id
    ).first()
    if not clinic:
        raise HTTPException(status_code=404, detail="Phòng khám không thuộc chuỗi này.")
    return PublicClinicOut(
        clinic_id=clinic.id, slug=clinic.slug, name=clinic.name, logo_url=clinic.logo_url,
        address=clinic.address, phone=clinic.phone, is_active=bool(clinic.is_active),
    )


@router.get("/resolve/{brand_slug}", response_model=PublicClinicOut,
            dependencies=[Depends(public_rate_limiter)])
@router.get("/resolve/{brand_slug}/{branch_slug}", response_model=PublicClinicOut,
            dependencies=[Depends(public_rate_limiter)])
def resolve_public_chat_target(brand_slug: str, branch_slug: str | None = None,
                               db: Session = Depends(get_db)):
    """Resolve a public /chat/<brand>[/<branch>] URL to the clinic to talk to.

    The public URL carries the brand (organization) and optionally a branch,
    never the clinic - but the chat API is clinic-scoped, so the slug has to be
    translated here. With a branch the mapping is exact; without one we fall
    back to the brand's first active clinic.
    """
    from backend.app.core.slug import resolve as resolve_slug

    clinic = None
    chosen: Branch | None = None
    if branch_slug:
        row = resolve_slug(db, branch_slug)
        if row and row.entity_type == "branch" and row.is_active:
            branch = db.query(Branch).filter(Branch.id == row.entity_id).first()
            if branch and branch.is_active:
                chosen = branch
                clinic = db.query(Clinic).filter(Clinic.id == branch.clinic_id).first()

    if clinic is None:
        row = resolve_slug(db, brand_slug)
        if row is None or not row.is_active:
            raise HTTPException(status_code=404, detail="Không tìm thấy phòng khám.")
        if row.entity_type == "clinic":
            clinic = db.query(Clinic).filter(Clinic.id == row.entity_id).first()
        elif row.entity_type == "organization":
            clinic = (
                db.query(Clinic)
                .filter(Clinic.organization_id == row.entity_id,
                        Clinic.is_active == True)  # noqa: E712
                .order_by(Clinic.id)
                .first()
            )

    if not clinic:
        raise HTTPException(status_code=404, detail="Không tìm thấy phòng khám.")

    return PublicClinicOut(
        clinic_id=clinic.id, slug=clinic.slug, name=clinic.name, logo_url=clinic.logo_url,
        address=clinic.address, phone=clinic.phone, is_active=bool(clinic.is_active),
        default_locale=clinic.default_locale or "vi",
        public_chat_v1_enabled=bool(clinic.public_chat_v1_enabled),
        branch=_branch_view(db, chosen) if chosen else None,
        branches=_active_branches(db, clinic.id),
    )


@router.get("/org-by-slug/{slug}", dependencies=[Depends(public_rate_limiter)])
def org_by_slug(slug: str, db: Session = Depends(get_db)):
    """Resolve a chain link /g/<slug> to the chain + its member clinics (each with its own link)."""
    org = db.query(Organization).filter(Organization.slug == slug).first()
    if not org:
        raise HTTPException(status_code=404, detail="Không tìm thấy chuỗi phòng khám.")
    clinics = db.query(Clinic).filter(Clinic.organization_id == org.id, Clinic.is_active == True).all()  # noqa: E712
    return {
        "name": org.name, "slug": org.slug,
        "clinics": [
            {"clinic_id": c.id, "slug": c.slug, "name": c.name, "address": c.address, "logo_url": c.logo_url}
            for c in clinics
        ],
    }

PAGE_TEMPLATE = """
<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CareDesk AI</title>
<style>
body{{font-family:system-ui,sans-serif;background:#f0fdfa;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
.card{{background:#fff;border-radius:16px;box-shadow:0 10px 30px rgba(0,0,0,.08);padding:40px;max-width:420px;text-align:center}}
.icon{{font-size:44px}}h2{{color:#0f172a;margin:12px 0 8px}}p{{color:#64748b;font-size:14px;line-height:1.5}}
</style></head><body><div class="card"><div class="icon">{icon}</div><h2>{title}</h2><p>{body}</p></div></body></html>
"""


def _get_valid_appointment(db: Session, appt_id: int, token: str) -> Appointment:
    if not verify_public_token(appt_id, token):
        raise HTTPException(status_code=403, detail="Liên kết không hợp lệ hoặc đã hết hạn.")
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Không tìm thấy lịch hẹn.")
    return appt


@router.get("/appointments/{appt_id}/confirm", response_class=HTMLResponse,
            dependencies=[Depends(public_rate_limiter)])
def public_confirm(appt_id: int, token: str = "", db: Session = Depends(get_db)):
    appt = _get_valid_appointment(db, appt_id, token)
    time_str = appt.start_time.strftime("%H:%M ngày %d/%m/%Y")

    if appt.status == "cancelled":
        return PAGE_TEMPLATE.format(icon="⚠️", title="Lịch hẹn đã bị hủy",
                                    body="Lịch hẹn này đã bị hủy trước đó. Vui lòng liên hệ phòng khám để đặt lại.")
    if appt.status == "pending":
        appt.status = "confirmed"
        log_action(db, None, "public_confirm", f"Khách tự xác nhận lịch hẹn #{appt.id}")
        db.commit()
        ws_manager.notify(appt.clinic_id, {"type": "appointment_update", "appointment_id": appt.id})

    return PAGE_TEMPLATE.format(
        icon="✅", title="Xác nhận lịch hẹn thành công!",
        body=f"Hẹn gặp bạn lúc <b>{time_str}</b> tại {appt.branch.name}.<br>Vui lòng đến trước 10 phút. Cảm ơn bạn!"
    )


@router.get("/appointments/{appt_id}/cancel", response_class=HTMLResponse,
            dependencies=[Depends(public_rate_limiter)])
def public_cancel(appt_id: int, token: str = "", db: Session = Depends(get_db)):
    appt = _get_valid_appointment(db, appt_id, token)

    if appt.status in ("pending", "awaiting_deposit", "confirmed"):
        old_status = appt.status
        appt.status = "cancelled"
        from backend.app.api.endpoints.appointment import handle_status_transition
        handle_status_transition(db, appt, old_status)
        log_action(db, None, "public_cancel", f"Khách tự hủy lịch hẹn #{appt.id}")
        db.commit()
        ws_manager.notify(appt.clinic_id, {"type": "appointment_update", "appointment_id": appt.id})

    return PAGE_TEMPLATE.format(
        icon="🗓️", title="Đã hủy lịch hẹn",
        body="Lịch hẹn của bạn đã được hủy thành công. Nếu muốn đặt lại, hãy nhắn tin cho trợ lý ảo hoặc gọi hotline phòng khám nhé."
    )


@router.get("/appointments/{appt_id}/reschedule", response_class=HTMLResponse,
            dependencies=[Depends(public_rate_limiter)])
def public_reschedule(appt_id: int, token: str = "", day: str = "", slot: str = "",
                      db: Session = Depends(get_db)):
    """Move an appointment instead of cancelling it.

    Without this the only options in a reminder are "confirm" and "cancel", so a
    patient who simply cannot make Thursday cancels — and a good share of them
    never rebook. Turning that cancellation into a different time is the cheapest
    booking the clinic will ever get.

    Same token as confirm/cancel: it already proves possession of the reminder,
    and asking a patient to log in to move an appointment loses more of them than
    it protects.
    """
    from backend.app.services.booking_flow import open_slots

    appt = _get_valid_appointment(db, appt_id, token)
    if appt.status in ("cancelled", "completed", "no_show"):
        return PAGE_TEMPLATE.format(
            icon="⚠️", title="Không đổi được lịch này",
            body="Lịch hẹn đã kết thúc hoặc đã bị hủy. Vui lòng liên hệ phòng khám để đặt lịch mới.")

    duration = (appt.service.duration_minutes if appt.service else 30) or 30
    base = f"{settings.PUBLIC_BASE_URL}{settings.API_V1_STR}/public/appointments/{appt.id}"

    # Step 2: a day and a time were picked — move it.
    if day and slot:
        try:
            target = date.fromisoformat(day)
            new_time = datetime.strptime(slot, "%H:%M").time()
        except ValueError:
            return PAGE_TEMPLATE.format(icon="⚠️", title="Dữ liệu không hợp lệ",
                                        body="Vui lòng chọn lại ngày giờ.")

        free = open_slots(db, appt.clinic_id, target, duration, branch_id=appt.branch_id)
        match = next((doc for s, doc in free if s == new_time), None)
        if not match:
            return PAGE_TEMPLATE.format(
                icon="⚠️", title="Khung giờ vừa chọn đã có người đặt",
                body=f'Vui lòng <a href="{base}/reschedule?token={token}">chọn giờ khác</a>.')

        old = appt.start_time.strftime("%H:%M %d/%m")
        appt.doctor_id = match.id
        appt.start_time = datetime.combine(target, new_time)
        appt.end_time = appt.start_time + timedelta(minutes=duration)
        # The old reminders described a time that no longer exists; drop them so
        # the scheduler sends fresh ones for the new slot.
        db.query(ReminderLog).filter(ReminderLog.appointment_id == appt.id).delete()
        log_action(db, None, "public_reschedule",
                   f"Khách tự đổi lịch #{appt.id}: {old} -> {slot} {target:%d/%m}")
        db.commit()
        ws_manager.notify(appt.clinic_id, {"type": "appointment_update", "appointment_id": appt.id})

        return PAGE_TEMPLATE.format(
            icon="✅", title="Đã đổi lịch hẹn",
            body=f"Lịch hẹn mới của bạn: <b>{slot} ngày {target:%d/%m/%Y}</b> "
                 f"tại {appt.branch.name}.<br>Hẹn gặp bạn!")

    # Step 1: offer the next few days that actually have room.
    today = clock.today()
    options = []
    for offset in range(14):
        d = today + timedelta(days=offset)
        slots = open_slots(db, appt.clinic_id, d, duration, branch_id=appt.branch_id)
        if not slots:
            continue
        buttons = "".join(
            f'<a href="{base}/reschedule?token={token}&day={d.isoformat()}'
            f'&slot={s:%H:%M}" style="display:inline-block;margin:3px;padding:7px 12px;'
            f'border:1px solid #0d9488;border-radius:7px;color:#0d9488;'
            f'text-decoration:none;font-size:14px">{s:%H:%M}</a>'
            for s, _ in slots[:12]
        )
        options.append(f'<div style="margin:14px 0"><b>{d:%d/%m/%Y}</b><br>{buttons}</div>')
        if len(options) >= 5:
            break

    if not options:
        return PAGE_TEMPLATE.format(
            icon="😔", title="Chưa có khung giờ trống",
            body="Hai tuần tới đã kín lịch. Vui lòng gọi hotline để phòng khám sắp xếp giúp bạn.")

    current = appt.start_time.strftime("%H:%M ngày %d/%m/%Y")
    return PAGE_TEMPLATE.format(
        icon="🗓️", title="Chọn giờ mới",
        body=f"Lịch hiện tại: <b>{current}</b>.<br>Chọn khung giờ bạn muốn đổi sang:"
             f'<div style="text-align:left">{"".join(options)}</div>')


# ---------- Deposit payment (mock gateway; VNPay/MoMo adapter-ready) ----------

@router.get("/payments/{payment_id}/pay", response_class=HTMLResponse,
            dependencies=[Depends(public_rate_limiter)])
def payment_page(payment_id: int, token: str = "", db: Session = Depends(get_db)):
    from backend.app.models.models import Payment
    from backend.app.services.payment_gateway import verify_payment_token

    if not verify_payment_token(payment_id, token):
        raise HTTPException(status_code=403, detail="Liên kết thanh toán không hợp lệ.")
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Không tìm thấy giao dịch.")

    if payment.status == "paid":
        return PAGE_TEMPLATE.format(icon="✅", title="Đã thanh toán",
                                    body="Khoản cọc này đã được thanh toán trước đó. Lịch hẹn của bạn đã được xác nhận!")

    body = f"""
        Số tiền cọc: <b style="font-size:22px;color:#0d9488">{payment.amount:,.0f}đ</b><br>
        (Được trừ trực tiếp vào hóa đơn dịch vụ)<br><br>
        <div style="border:1px dashed #cbd5e1;border-radius:12px;padding:18px;margin-bottom:16px">
            <b>QR thanh toán (mô phỏng)</b><br>
            <span style="font-size:52px">▦</span><br>
            <small>Môi trường demo — tích hợp VNPay/MoMo khi lên production</small>
        </div>
        <form method="post" action="{settings.API_V1_STR}/public/payments/{payment.id}/confirm?token={token}">
            <button type="submit" style="background:#0d9488;color:#fff;border:none;border-radius:10px;
                padding:14px 28px;font-size:15px;font-weight:600;cursor:pointer">
                Tôi đã thanh toán {payment.amount:,.0f}đ
            </button>
        </form>
    """
    return PAGE_TEMPLATE.format(icon="💳", title="Đặt cọc giữ chỗ lịch hẹn", body=body)


@router.post("/payments/{payment_id}/confirm", response_class=HTMLResponse,
             dependencies=[Depends(public_rate_limiter)])
def payment_confirm(payment_id: int, token: str = "", db: Session = Depends(get_db)):
    from backend.app.models.models import Payment
    from backend.app.services.payment_gateway import verify_payment_token, mark_paid
    from backend.app.services.capi import send_capi_event

    if not verify_payment_token(payment_id, token):
        raise HTTPException(status_code=403, detail="Liên kết thanh toán không hợp lệ.")
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Không tìm thấy giao dịch.")

    mark_paid(db, payment)
    log_action(db, None, "deposit_paid", f"Khách thanh toán cọc {payment.amount:,.0f}đ (giao dịch #{payment.id})")
    db.commit()
    ws_manager.notify(payment.clinic_id, {"type": "appointment_update", "appointment_id": payment.appointment_id})

    # Meta ads optimization signal: money moved
    try:
        appt = db.query(Appointment).filter(Appointment.id == payment.appointment_id).first() if payment.appointment_id else None
        patient = appt.patient if appt else None
        send_capi_event(db, payment.clinic_id, "Purchase",
                        phone=patient.phone if patient else None, value=payment.amount)
    except Exception as e:
        print(f"[CAPI] skipped: {e}")

    return PAGE_TEMPLATE.format(
        icon="🎉", title="Thanh toán thành công!",
        body="Lịch hẹn của bạn đã được <b>XÁC NHẬN</b>. Khoản cọc sẽ được trừ vào hóa đơn khi bạn đến khám. Hẹn gặp bạn tại phòng khám!"
    )
