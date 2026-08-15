"""
Automatic appointment reminder scheduler.
A background task wakes up every REMINDER_CHECK_INTERVAL_SECONDS, finds
appointments starting within the next 24h / 2h that have not been reminded yet,
and notifies the patient via email + ZNS/SMS (mock when not configured).
Reminder messages carry tokenized public confirm/cancel links so patients can
self-confirm without logging in -> directly attacks the no-show rate.
"""
import asyncio
import hashlib
import hmac
import logging
from datetime import datetime, timedelta
from backend.app.core.config import settings
from backend.app.core.database import SessionLocal
from backend.app.models.models import Appointment, ReminderLog
from backend.app.services.channel_gateway import CHANNEL_NONE, send_zns_or_sms
from backend.app.core import clock

logger = logging.getLogger(__name__)

REMINDER_KINDS = [("24h", 24), ("2h", 2)]


def make_public_token(appointment_id: int) -> str:
    """Short HMAC token authorizing public confirm/cancel for one appointment."""
    digest = hmac.new(
        settings.SECRET_KEY.encode(), f"appt:{appointment_id}".encode(), hashlib.sha256
    ).hexdigest()
    return digest[:20]


def verify_public_token(appointment_id: int, token: str) -> bool:
    return hmac.compare_digest(make_public_token(appointment_id), token or "")


def build_reminder_fields(appt: Appointment) -> dict:
    """The reminder decomposed into named facts.

    SMS takes a sentence; a ZBS template takes named variables and has no
    free-text field at all, so the same information has to be available in
    pieces. The clinic maps its own approved template's variable names onto
    these — see channel_gateway.TEMPLATE_FIELDS_DOC.
    """
    token = make_public_token(appt.id)
    base = f"{settings.PUBLIC_BASE_URL}{settings.API_V1_STR}/public/appointments/{appt.id}"
    return {
        "patient_name": appt.patient.full_name if appt.patient else "",
        "clinic_name": appt.branch.clinic.name if appt.branch and appt.branch.clinic else "",
        "branch_name": appt.branch.name if appt.branch else "",
        "branch_address": appt.branch.address if appt.branch else "",
        "service_name": appt.service.name if appt.service else "",
        "doctor_name": appt.doctor.name if appt.doctor else "",
        "date": appt.start_time.strftime("%d/%m/%Y"),
        "time": appt.start_time.strftime("%H:%M"),
        "confirm_url": f"{base}/confirm?token={token}",
        "cancel_url": f"{base}/cancel?token={token}",
        # Offering a move next to the cancel link turns "I can't make Thursday"
        # into a different appointment rather than a lost one.
        "reschedule_url": f"{base}/reschedule?token={token}",
    }


def reminder_tracking_id(appt: Appointment, kind: str) -> str:
    """Required by ZBS, and the only way a delivery record on Zalo's side maps
    back to the row that produced it. Stable per (appointment, kind) so a retry
    is recognisable as the same message rather than a new one."""
    return f"caredesk-{appt.id}-{kind}"


def build_reminder_text(appt: Appointment, kind: str) -> str:
    time_str = appt.start_time.strftime("%H:%M ngày %d/%m/%Y")
    when = "ngày mai" if kind == "24h" else "sắp tới trong 2 giờ nữa"
    token = make_public_token(appt.id)
    confirm_url = f"{settings.PUBLIC_BASE_URL}{settings.API_V1_STR}/public/appointments/{appt.id}/confirm?token={token}"
    cancel_url = f"{settings.PUBLIC_BASE_URL}{settings.API_V1_STR}/public/appointments/{appt.id}/cancel?token={token}"
    reschedule_url = f"{settings.PUBLIC_BASE_URL}{settings.API_V1_STR}/public/appointments/{appt.id}/reschedule?token={token}"
    return (
        f"CareDesk nhắc lịch: Bạn có lịch hẹn {when} - {appt.service.name} "
        f"với {appt.doctor.name} lúc {time_str} tại {appt.branch.name}. "
        f"Xác nhận: {confirm_url} | Đổi giờ: {reschedule_url} | Hủy lịch: {cancel_url}"
    )


#: How many times one reminder is attempted on one medium before we stop. The
#: scheduler wakes every REMINDER_CHECK_INTERVAL_SECONDS, so without a ceiling a
#: permanently failing send is retried hundreds of times before the appointment
#: even arrives — free while nothing is configured, billed per attempt once a
#: real SMS gateway is in place.
MAX_SEND_ATTEMPTS = 3


def _open_outbox_entry(db, appointment_id: int, kind: str, medium: str):
    """The outbox row to attempt now, or None if this one is finished.

    Finished means either already sent, or failed as many times as we allow.
    Creates the row on first attempt so a failure is still on record — the whole
    point of an outbox is that "we tried and it did not work" is visible rather
    than being indistinguishable from "we never got round to it".
    """
    entry = db.query(ReminderLog).filter(
        ReminderLog.appointment_id == appointment_id,
        ReminderLog.kind == kind,
        ReminderLog.medium == medium,
    ).first()

    if entry is None:
        entry = ReminderLog(appointment_id=appointment_id, kind=kind, medium=medium,
                            channel=CHANNEL_NONE, status="failed", attempts=0)
        db.add(entry)
        return entry

    if entry.status == "sent" or entry.attempts >= MAX_SEND_ATTEMPTS:
        return None
    return entry


def _record(entry: ReminderLog, delivered: bool, channel: str, detail: str,
            attempted: bool = True, retryable: bool = True) -> None:
    entry.channel = channel
    if attempted:
        # Only a real attempt counts. A missing channel is a config gap, not a
        # failed delivery — charging it an attempt would retire every reminder
        # that queued up while the clinic was waiting for its Zalo OA.
        entry.attempts += 1

    if delivered:
        entry.status = "sent"
        entry.last_error = None
        return

    entry.status = "failed"
    entry.last_error = detail[:500]
    if attempted and not retryable:
        # The provider evaluated this message and refused it. Retrying buys the
        # same rejection at the same price, so stop here.
        entry.attempts = MAX_SEND_ATTEMPTS


async def check_and_send_reminders():
    """One scheduler tick: scan upcoming appointments and send pending reminders."""
    from backend.app.api.endpoints.appointment import send_email_notification

    db = SessionLocal()
    sent_count = 0
    undelivered = 0
    try:
        now = clock.now()
        for kind, hours in REMINDER_KINDS:
            window_end = now + timedelta(hours=hours)
            candidates = db.query(Appointment).filter(
                Appointment.status.in_(["pending", "confirmed"]),
                Appointment.start_time > now,
                Appointment.start_time <= window_end
            ).all()

            for appt in candidates:
                text = build_reminder_text(appt, kind)
                patient = appt.patient
                if not patient:
                    continue

                if patient.phone:
                    entry = _open_outbox_entry(db, appt.id, kind, "phone")
                    if entry is not None:
                        result = send_zns_or_sms(
                            db, appt.clinic_id, patient.phone, text,
                            tracking_id=reminder_tracking_id(appt, kind),
                            template_fields=build_reminder_fields(appt),
                        )
                        _record(entry, result.delivered, result.channel, result.detail,
                                attempted=result.attempted, retryable=result.retryable)
                        sent_count += result.delivered
                        undelivered += not result.delivered

                if patient.email:
                    entry = _open_outbox_entry(db, appt.id, kind, "email")
                    if entry is not None:
                        html = text.replace(" | ", "<br>").replace("Xác nhận: ", "<br><b>Xác nhận:</b> ").replace("Hủy lịch: ", "<b>Hủy lịch:</b> ")
                        smtp_ready = bool(settings.SMTP_USER and settings.SMTP_PASSWORD)
                        ok = await send_email_notification(
                            patient.email, "CareDesk AI - Nhắc lịch hẹn khám", f"<p>{html}</p>"
                        )
                        _record(entry, ok, "email" if ok else CHANNEL_NONE,
                                "" if ok else ("SMTP gửi lỗi" if smtp_ready
                                               else "SMTP chưa cấu hình"),
                                attempted=smtp_ready)
                        sent_count += ok
                        undelivered += not ok

                db.commit()
    except Exception:
        logger.exception("Reminder scheduler tick failed")
        db.rollback()
    finally:
        db.close()

    if undelivered:
        logger.warning(
            "%s lời nhắc chưa gửi được ở lượt này (chưa cấu hình kênh, hoặc nhà "
            "cung cấp từ chối). Xem bảng reminder_logs để biết lý do từng ca.",
            undelivered,
        )
    return sent_count


async def send_daily_digest():
    """8h/20h digest to the clinic owner: today's numbers pushed into their pocket."""
    from backend.app.core.roles import ROLE_OWNER
    from backend.app.models.models import Clinic, User, Appointment, Conversation, RevenueRecord
    from backend.app.api.endpoints.appointment import send_email_notification

    db = SessionLocal()
    try:
        now = clock.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        clinics = db.query(Clinic).filter(Clinic.digest_enabled == True).all()  # noqa: E712
        for clinic in clinics:
            appts = db.query(Appointment).filter(
                Appointment.clinic_id == clinic.id,
                Appointment.start_time >= start,
                Appointment.start_time <= start + timedelta(days=1)
            ).all()
            convs = db.query(Conversation).filter(
                Conversation.clinic_id == clinic.id, Conversation.created_at >= start
            ).count()
            revenue = db.query(RevenueRecord).filter(
                RevenueRecord.clinic_id == clinic.id, RevenueRecord.recorded_at >= start
            ).all()
            ai_booked = sum(1 for a in appts if (a.booking_source or "").startswith("ai_"))
            pending = sum(1 for a in appts if a.status in ("pending", "awaiting_deposit"))

            text = (f"CareDesk digest {now.strftime('%d/%m %H:%M')} - {clinic.name}: "
                    f"{len(appts)} lich hen hom nay ({pending} cho xac nhan, AI chot {ai_booked}), "
                    f"{convs} hoi thoai moi, doanh thu ghi nhan {sum(r.amount for r in revenue):,.0f}d "
                    f"(AI: {sum(r.amount for r in revenue if (r.source or '').startswith('ai_')):,.0f}d).")

            if clinic.phone:
                send_zns_or_sms(db, clinic.id, clinic.phone, text)
            # Every owner, not just the first one found. A clinic can legitimately
            # have several — co-founders, or a manager folded in from the retired
            # "admin" role (migration c9d0e1f2a3b4) — and picking .first() silently
            # left the rest out of the daily numbers.
            owners = db.query(User).filter(
                User.clinic_id == clinic.id,
                User.role == ROLE_OWNER,
                User.is_active == True,  # noqa: E712
            ).all()
            for owner in owners:
                await send_email_notification(owner.email, "CareDesk AI - Ban tin van hanh", f"<p>{text}</p>")
    except Exception:
        logger.exception("Daily digest failed")
    finally:
        db.close()


async def reminder_loop():
    """Unified background scheduler: reminders + automation engine + daily digest."""
    from backend.app.services.events import run_engine_tick, run_recurring_rules
    from backend.app.services.payment_gateway import release_expired_holds

    logger.info("Scheduler started (every %ss)", settings.REMINDER_CHECK_INTERVAL_SECONDS)
    last_recurring_run = None
    last_digest_slot = None

    while True:
        await check_and_send_reminders()

        # Automation engine: process events -> schedule -> dispatch
        db = SessionLocal()
        try:
            # Free abandoned deposit holds first, so the slot is already back on
            # the market when the waitlist automation runs in the same tick.
            release_expired_holds(db)
            run_engine_tick(db)
            now = clock.now()
            # Recurring rules (win-back, package expiry): once per hour is plenty
            if last_recurring_run is None or (now - last_recurring_run).total_seconds() > 3600:
                run_recurring_rules(db)
                last_recurring_run = now
        except Exception:
            logger.exception("Automation engine tick failed")
        finally:
            db.close()

        # Owner digest at 08h and 20h (once per slot)
        now = clock.now()
        slot = (now.date(), 8 if now.hour < 20 else 20)
        if now.hour in (8, 20) and slot != last_digest_slot:
            await send_daily_digest()
            last_digest_slot = slot

        await asyncio.sleep(settings.REMINDER_CHECK_INTERVAL_SECONDS)
