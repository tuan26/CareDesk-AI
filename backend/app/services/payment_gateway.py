"""
Payment gateway abstraction for deposits & package sales.
Default provider is a mock QR page (fully demo-able offline). Plug VNPay/MoMo
by implementing `create_payment_url` for the real provider - the rest of the
system only talks to this module.
"""
import hashlib
import hmac
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from backend.app.core.config import settings
from backend.app.models.models import Payment, Appointment
from backend.app.services.events import emit_event


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


def mark_paid(db: Session, payment: Payment, provider_ref: Optional[str] = None):
    """Confirm a payment: deposit -> appointment becomes confirmed + events fire."""
    if payment.status == "paid":
        return
    payment.status = "paid"
    payment.paid_at = datetime.now()
    payment.provider_ref = provider_ref or f"MOCK-{payment.id}"

    if payment.purpose == "deposit" and payment.appointment_id:
        appt = db.query(Appointment).filter(Appointment.id == payment.appointment_id).first()
        if appt and appt.status in ("pending", "awaiting_deposit"):
            appt.status = "confirmed"
        emit_event(db, payment.clinic_id, "deposit_paid", patient_id=payment.patient_id,
                   payload={"appointment_id": payment.appointment_id, "amount": payment.amount})

    db.commit()
