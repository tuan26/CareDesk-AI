"""
Public (no-login) endpoints reached from reminder messages:
tokenized one-click confirm / cancel links for patients.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.models.models import Appointment, Clinic, Organization
from backend.app.schemas.schemas import PublicClinicOut
from backend.app.services.reminder import verify_public_token
from backend.app.services.rate_limit import public_rate_limiter
from backend.app.services.audit import log_action
from backend.app.services.ws_manager import ws_manager

router = APIRouter()


# ---------- Per-clinic / per-chain public link resolution (slug -> tenant) ----------

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
