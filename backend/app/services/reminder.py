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
from datetime import datetime, timedelta
from backend.app.core.config import settings
from backend.app.core.database import SessionLocal
from backend.app.models.models import Appointment, ReminderLog
from backend.app.services.channel_gateway import send_zns_or_sms

REMINDER_KINDS = [("24h", 24), ("2h", 2)]


def make_public_token(appointment_id: int) -> str:
    """Short HMAC token authorizing public confirm/cancel for one appointment."""
    digest = hmac.new(
        settings.SECRET_KEY.encode(), f"appt:{appointment_id}".encode(), hashlib.sha256
    ).hexdigest()
    return digest[:20]


def verify_public_token(appointment_id: int, token: str) -> bool:
    return hmac.compare_digest(make_public_token(appointment_id), token or "")


def build_reminder_text(appt: Appointment, kind: str) -> str:
    time_str = appt.start_time.strftime("%H:%M ngày %d/%m/%Y")
    when = "ngày mai" if kind == "24h" else "sắp tới trong 2 giờ nữa"
    token = make_public_token(appt.id)
    confirm_url = f"{settings.PUBLIC_BASE_URL}{settings.API_V1_STR}/public/appointments/{appt.id}/confirm?token={token}"
    cancel_url = f"{settings.PUBLIC_BASE_URL}{settings.API_V1_STR}/public/appointments/{appt.id}/cancel?token={token}"
    return (
        f"CareDesk nhắc lịch: Bạn có lịch hẹn {when} - {appt.service.name} "
        f"với {appt.doctor.name} lúc {time_str} tại {appt.branch.name}. "
        f"Xác nhận: {confirm_url} | Hủy lịch: {cancel_url}"
    )


async def check_and_send_reminders():
    """One scheduler tick: scan upcoming appointments and send pending reminders."""
    from backend.app.api.endpoints.appointment import send_email_notification

    db = SessionLocal()
    sent_count = 0
    try:
        now = datetime.now()
        for kind, hours in REMINDER_KINDS:
            window_end = now + timedelta(hours=hours)
            candidates = db.query(Appointment).filter(
                Appointment.status.in_(["pending", "confirmed"]),
                Appointment.start_time > now,
                Appointment.start_time <= window_end
            ).all()

            for appt in candidates:
                already = db.query(ReminderLog).filter(
                    ReminderLog.appointment_id == appt.id,
                    ReminderLog.kind == kind
                ).first()
                if already:
                    continue

                text = build_reminder_text(appt, kind)
                patient = appt.patient

                if patient and patient.phone:
                    channel = send_zns_or_sms(db, appt.clinic_id, patient.phone, text)
                    db.add(ReminderLog(appointment_id=appt.id, kind=kind, channel=channel))
                    sent_count += 1

                if patient and patient.email:
                    html = text.replace(" | ", "<br>").replace("Xác nhận: ", "<br><b>Xác nhận:</b> ").replace("Hủy lịch: ", "<b>Hủy lịch:</b> ")
                    await send_email_notification(
                        patient.email, "CareDesk AI - Nhắc lịch hẹn khám", f"<p>{html}</p>"
                    )
                    db.add(ReminderLog(appointment_id=appt.id, kind=kind, channel="email"))
                    sent_count += 1

                db.commit()
    except Exception as e:
        print(f"[REMINDER ERROR] {e}")
        db.rollback()
    finally:
        db.close()
    return sent_count


async def send_daily_digest():
    """8h/20h digest to the clinic owner: today's numbers pushed into their pocket."""
    from backend.app.models.models import Clinic, User, Appointment, Conversation, RevenueRecord
    from backend.app.api.endpoints.appointment import send_email_notification

    db = SessionLocal()
    try:
        now = datetime.now()
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
            owner = db.query(User).filter(User.clinic_id == clinic.id, User.role == "owner").first()
            if owner:
                await send_email_notification(owner.email, "CareDesk AI - Ban tin van hanh", f"<p>{text}</p>")
    except Exception as e:
        print(f"[DIGEST ERROR] {e}")
    finally:
        db.close()


async def reminder_loop():
    """Unified background scheduler: reminders + automation engine + daily digest."""
    from backend.app.services.events import run_engine_tick, run_recurring_rules

    print(f"[SCHEDULER] started (every {settings.REMINDER_CHECK_INTERVAL_SECONDS}s)")
    last_recurring_run = None
    last_digest_slot = None

    while True:
        await check_and_send_reminders()

        # Automation engine: process events -> schedule -> dispatch
        db = SessionLocal()
        try:
            run_engine_tick(db)
            now = datetime.now()
            # Recurring rules (win-back, package expiry): once per hour is plenty
            if last_recurring_run is None or (now - last_recurring_run).total_seconds() > 3600:
                run_recurring_rules(db)
                last_recurring_run = now
        except Exception as e:
            print(f"[ENGINE ERROR] {e}")
        finally:
            db.close()

        # Owner digest at 08h and 20h (once per slot)
        now = datetime.now()
        slot = (now.date(), 8 if now.hour < 20 else 20)
        if now.hour in (8, 20) and slot != last_digest_slot:
            await send_daily_digest()
            last_digest_slot = slot

        await asyncio.sleep(settings.REMINDER_CHECK_INTERVAL_SECONDS)
