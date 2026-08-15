"""
Payment gateway abstraction for deposits & package sales.
Default provider is a mock QR page (fully demo-able offline). Plug VNPay/MoMo
by implementing `create_payment_url` for the real provider - the rest of the
system only talks to this module.
"""
import hashlib
import hmac
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from backend.app.core.config import settings
from backend.app.core.booking_rules import (
    STATUS_AWAITING_DEPOSIT, STATUS_CANCELLED, STATUS_CONFIRMED, STATUS_PENDING,
)
from backend.app.models.models import Payment, Appointment, Clinic
from backend.app.services.events import emit_event
from backend.app.core import clock

logger = logging.getLogger(__name__)


def make_payment_token(payment_id: int) -> str:
    digest = hmac.new(settings.SECRET_KEY.encode(), f"pay:{payment_id}".encode(), hashlib.sha256).hexdigest()
    return digest[:20]


def verify_payment_token(payment_id: int, token: str) -> bool:
    return hmac.compare_digest(make_payment_token(payment_id), token or "")


def create_deposit_payment(db: Session, appointment: Appointment, amount: float) -> Payment:
    payment = Payment(
        clinic_id=appointment.clinic_id,
        patient_id=appointment.patient_id,
        appointment_id=appointment.id,
        amount=amount,
        purpose="deposit",
        method="mock_qr",
        status="pending"
    )
    db.add(payment)
    db.flush()
    return payment


def payment_url(payment: Payment) -> str:
    return (f"{settings.PUBLIC_BASE_URL}{settings.API_V1_STR}/public/payments/"
            f"{payment.id}/pay?token={make_payment_token(payment.id)}")


def hold_for_deposit(db: Session, appointment: Appointment,
                     clinic: Optional[Clinic]) -> Tuple[Optional[Payment], Optional[str]]:
    """Put an appointment on a deposit hold, if this clinic collects deposits.

    Returns (payment, payment_url), or (None, None) when deposits are off — in
    which case the appointment keeps whatever status it already had.

    The hold has a deadline. Without one, a patient who opens the payment page
    and wanders off keeps a prime evening slot locked indefinitely, and the
    clinic never learns why their calendar looks full.
    """
    amount = (clinic.deposit_amount or 0) if clinic else 0
    if amount <= 0:
        return None, None

    appointment.status = STATUS_AWAITING_DEPOSIT
    appointment.hold_expires_at = clock.now() + timedelta(
        minutes=settings.DEPOSIT_HOLD_MINUTES
    )
    payment = create_deposit_payment(db, appointment, amount)
    return payment, payment_url(payment)


def release_expired_holds(db: Session) -> int:
    """Cancel deposit holds whose deadline has passed and free the slot.

    Emits appointment_cancelled so the waitlist automation gets its chance at
    the freed slot — the same path a real cancellation takes.
    """
    now = clock.now()
    stale = db.query(Appointment).filter(
        Appointment.status == STATUS_AWAITING_DEPOSIT,
        Appointment.hold_expires_at != None,       # noqa: E711
        Appointment.hold_expires_at <= now,
    ).all()

    for appt in stale:
        appt.status = STATUS_CANCELLED
        appt.note = ((appt.note or "") + " [Tự huỷ: quá hạn đặt cọc giữ chỗ]").strip()
        emit_event(db, appt.clinic_id, "appointment_cancelled", patient_id=appt.patient_id,
                   payload={"appointment_id": appt.id, "reason": "deposit_hold_expired",
                            "service_id": appt.service_id,
                            "date": appt.start_time.strftime("%d/%m/%Y"),
                            "slot": appt.start_time.strftime("%H:%M")})
    if stale:
        db.commit()
        logger.info("Đã nhả %s chỗ giữ quá hạn đặt cọc", len(stale))
    return len(stale)


def mark_paid(db: Session, payment: Payment, provider_ref: Optional[str] = None):
    """Confirm a payment: deposit -> appointment becomes confirmed + events fire."""
    if payment.status == "paid":
        return
    payment.status = "paid"
    payment.paid_at = clock.now()
    payment.provider_ref = provider_ref or f"MOCK-{payment.id}"

    if payment.purpose == "deposit" and payment.appointment_id:
        appt = db.query(Appointment).filter(Appointment.id == payment.appointment_id).first()
        if appt and appt.status in (STATUS_PENDING, STATUS_AWAITING_DEPOSIT):
            appt.status = STATUS_CONFIRMED
            appt.hold_expires_at = None  # paid: the hold is now a real booking
        emit_event(db, payment.clinic_id, "deposit_paid", patient_id=payment.patient_id,
                   payload={"appointment_id": payment.appointment_id, "amount": payment.amount})

    db.commit()
