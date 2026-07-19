"""
Rule-based booking state machine: lets the AI receptionist take a booking
end-to-end inside the chat (collect info -> propose real free slots -> create
a pending Appointment). Works fully offline (no LLM required); the state is
persisted on Conversation.booking_state.
"""
import re
from datetime import date, datetime, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session
from backend.app.models.models import (
    Conversation, PatientLead, Service, Doctor, WorkingSchedule, Branch, Appointment,
    Clinic, WaitlistEntry, ScheduledAction
)
from backend.app.services.events import emit_event

BOOKING_INTENT_KEYWORDS = ["đặt lịch", "đặt hẹn", "book lịch", "muốn hẹn", "lịch hẹn", "đăng ký khám"]
CANCEL_KEYWORDS = ["hủy đặt lịch", "không đặt nữa", "thôi không đặt", "hủy luôn"]
FAQ_KEYWORDS = ["giá", "bao nhiêu", "phí", "địa chỉ", "ở đâu", "mấy giờ", "mở cửa", "chi nhánh"]

SERVICE_KEYWORD_MAP = [
    (["nặn mụn", "trị mụn", "mụn"], "Điều trị mụn Chuẩn Y Khoa"),
    (["laser", "sẹo", "co2"], "Laser Fractional CO2 trị sẹo rỗ"),
    (["khám", "soi da", "bác sĩ"], "Khám da liễu với Bác sĩ chuyên khoa"),
]

WEEKDAY_PATTERNS = [
    (r"thứ\s*2|thu\s*2", 0), (r"thứ\s*3|thu\s*3", 1), (r"thứ\s*4|thu\s*4", 2),
    (r"thứ\s*5|thu\s*5", 3), (r"thứ\s*6|thu\s*6", 4), (r"thứ\s*7|thu\s*7", 5),
    (r"chủ\s*nhật|chu\s*nhat|\bcn\b", 6),
]


def _parse_date(text_lower: str) -> Optional[str]:
    """Parse a target date from Vietnamese text. Returns ISO date string."""
    today = date.today()
    if "ngày kia" in text_lower:
        return (today + timedelta(days=2)).isoformat()
    if "mai" in text_lower:
        return (today + timedelta(days=1)).isoformat()
    if "hôm nay" in text_lower or "bữa nay" in text_lower:
        return today.isoformat()

    for pattern, weekday in WEEKDAY_PATTERNS:
        if re.search(pattern, text_lower):
            days_ahead = (weekday - today.weekday()) % 7
            return (today + timedelta(days=days_ahead)).isoformat()

    # dd/mm or dd-mm (optionally /yyyy)
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{4}))?\b", text_lower)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        try:
            parsed = date(year, month, day)
            if parsed < today and not m.group(3):
                parsed = date(year + 1, month, day)
            return parsed.isoformat()
        except ValueError:
            return None
    return None


def _parse_time(text_lower: str) -> Optional[str]:
    """Parse 'HH:MM' from '9h', '9 giờ 30', '14:30'..."""
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", text_lower)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    m = re.search(r"\b(\d{1,2})\s*(?:h|giờ)(?:\s*(\d{2}))?", text_lower)
    if m:
        minute = int(m.group(2)) if m.group(2) else 0
        return f"{int(m.group(1)):02d}:{minute:02d}"
    return None


def _parse_phone(text: str) -> Optional[str]:
    m = re.search(r"\b(0[35789]\d{8})\b", text)
    return m.group(1) if m else None


def _parse_name(text: str) -> Optional[str]:
    m = re.search(r"(?:tên tôi là|tên là|mình là|tôi là|xưng là|gọi tôi là)\s+([A-ZÀ-Ỹa-zà-ỹ][A-ZÀ-Ỹa-zà-ỹ\s]{1,30})", text, re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        # Cut trailing verbs the regex may swallow
        name = re.split(r"\s+(?:muốn|cần|đặt|xin|nhé|ạ)\b", name)[0].strip()
        return name if len(name) >= 2 else None
    return None


def _resolve_service(db: Session, clinic_id: Optional[int], text_lower: str) -> Optional[Service]:
    query = db.query(Service)
    if clinic_id:
        query = query.filter(Service.clinic_id == clinic_id)
    services = query.all()
    if not services:
        return None

    # 1. Known keyword mapping (matches the seeded catalogue)
    for keywords, target_name in SERVICE_KEYWORD_MAP:
        if any(kw in text_lower for kw in keywords):
            for s in services:
                if s.name == target_name:
                    return s
            break

    # 2. Fuzzy: service whose name words appear in the text
    best, best_hits = None, 0
    for s in services:
        hits = sum(1 for w in s.name.lower().split() if len(w) > 2 and w in text_lower)
        if hits > best_hits:
            best, best_hits = s, hits
    return best if best_hits >= 2 else None


def _pick_doctor_and_slots(db: Session, clinic_id: Optional[int], target_date: date, duration: int):
    """Find an active doctor with free slots on the date. Returns (doctor, branch, slots)."""
    from backend.app.services.ai_engine import get_available_slots

    weekday = target_date.weekday()
    query = db.query(Doctor).filter(Doctor.is_active == True)  # noqa: E712
    if clinic_id:
        query = query.filter(Doctor.clinic_id == clinic_id)
    for doctor in query.all():
        has_schedule = db.query(WorkingSchedule).filter(
            WorkingSchedule.doctor_id == doctor.id,
            WorkingSchedule.day_of_week == weekday
        ).first()
        if not has_schedule:
            continue
        slots = get_available_slots(db, doctor.id, target_date, duration)
        if slots:
            branch = db.query(Branch).filter(Branch.id == (doctor.branch_id or has_schedule.branch_id)).first()
            return doctor, branch, [s.strftime("%H:%M") for s in slots]
    return None, None, []


def _fmt_date_vn(iso_date: str) -> str:
    d = date.fromisoformat(iso_date)
    days = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]
    return f"{days[d.weekday()]} ngày {d.strftime('%d/%m/%Y')}"


def handle_booking(db: Session, conv: Conversation, user_message: str) -> Optional[str]:
    """
    Advance the booking state machine with a new patient message.
    Returns the bot response text, or None if this message is not booking-related
    (caller falls through to FAQ / LLM handling).
    """
    state = dict(conv.booking_state or {})
    text_lower = user_message.lower()
    has_intent = any(kw in text_lower for kw in BOOKING_INTENT_KEYWORDS)

    if not state.get("active") and not has_intent:
        return None

    # Cancel the flow
    if state.get("active") and any(kw in text_lower for kw in CANCEL_KEYWORDS):
        conv.booking_state = {"active": False}
        db.commit()
        return "Dạ, tôi đã hủy yêu cầu đặt lịch. Nếu bạn cần hỗ trợ thêm về dịch vụ hoặc muốn đặt lại lịch hẹn, cứ nhắn cho tôi nhé!"

    # Extract entities from this message
    new_service = _resolve_service(db, conv.clinic_id, text_lower)
    new_date = _parse_date(text_lower)
    new_time = _parse_time(text_lower)
    new_phone = _parse_phone(user_message)
    new_name = _parse_name(user_message)

    # Mid-flow FAQ question with no new booking info -> let FAQ engine answer, keep state
    if state.get("active") and not has_intent and not any([new_service, new_date, new_time, new_phone, new_name]) \
            and any(kw in text_lower for kw in FAQ_KEYWORDS):
        return None

    if not state.get("active"):
        state = {"active": True}

    if new_service:
        state["service_id"] = new_service.id
    if new_date:
        state["date"] = new_date
        state.pop("proposed_slots", None)
        state.pop("slot", None)
    if new_phone:
        state["phone"] = new_phone
    if new_name:
        state["full_name"] = new_name

    # Backfill identity from the lead (widget consent form already collected it)
    lead: PatientLead = conv.patient
    if lead:
        if not state.get("full_name") and lead.full_name:
            state["full_name"] = lead.full_name
        if not state.get("phone") and lead.phone:
            state["phone"] = lead.phone

    # Slot selection: "1"/"2"/"3" referencing proposal, or explicit time in the proposed list
    proposed: List[str] = state.get("proposed_slots") or []
    if proposed and not state.get("slot"):
        choice_match = re.fullmatch(r"\s*(\d)\s*\.?\s*", user_message)
        if choice_match and 1 <= int(choice_match.group(1)) <= len(proposed):
            state["slot"] = proposed[int(choice_match.group(1)) - 1]
        elif new_time and new_time in proposed:
            state["slot"] = new_time
        elif new_time and new_time not in proposed:
            conv.booking_state = state
            db.commit()
            return (f"Rất tiếc khung giờ {new_time} không còn trống. "
                    f"Các khung giờ hiện có: {', '.join(proposed)}. Bạn vui lòng chọn lại giúp tôi nhé.")

    service = db.query(Service).filter(Service.id == state.get("service_id")).first() if state.get("service_id") else None

    # --- Decide the next question / action ---
    if not service:
        query = db.query(Service)
        if conv.clinic_id:
            query = query.filter(Service.clinic_id == conv.clinic_id)
        listing = "\n".join(f"- {s.name} ({s.price:,.0f}đ)" for s in query.all())
        conv.booking_state = state
        db.commit()
        return (f"Dạ, tôi rất sẵn lòng hỗ trợ bạn đặt lịch hẹn! Phòng khám hiện có các dịch vụ:\n{listing}\n"
                f"Bạn muốn đặt lịch dịch vụ nào ạ?")

    # Waitlist opt-in: patient answered "chờ" after we offered the waitlist
    if state.get("waitlist_offered") and re.search(r"\bchờ\b|danh sách chờ|waitlist", text_lower):
        db.add(WaitlistEntry(
            clinic_id=conv.clinic_id, patient_id=conv.patient_id,
            service_id=service.id, preferred_date=state.get("waitlist_date")
        ))
        state.pop("waitlist_offered", None)
        state.pop("waitlist_date", None)
        conv.booking_state = state
        db.commit()
        return (f"Dạ, tôi đã thêm bạn vào danh sách chờ cho {service.name}. "
                f"Ngay khi có khách hủy lịch và trống chỗ, tôi sẽ nhắn bạn đầu tiên để giữ ca nhé!")

    if not state.get("full_name") or not state.get("phone"):
        missing = []
        if not state.get("full_name"):
            missing.append("Họ tên")
        if not state.get("phone"):
            missing.append("Số điện thoại")
        conv.booking_state = state
        db.commit()
        return (f"Dạ, tôi đã ghi nhận thông tin bạn muốn đặt lịch dịch vụ {service.name}. "
                f"Bạn vui lòng cung cấp giúp tôi: {', '.join(missing)} để hoàn tất đăng ký nhé ạ.")

    if not state.get("date"):
        conv.booking_state = state
        db.commit()
        return (f"Dạ, tôi đã ghi nhận thông tin đặt lịch:\n"
                f"- Họ tên: {state['full_name']}\n"
                f"- Số điện thoại: {state['phone']}\n"
                f"- Dịch vụ: {service.name}\n"
                f"Bạn muốn đặt lịch vào ngày nào ạ? (ví dụ: ngày mai, thứ 7, hoặc 25/07)")

    target_date = date.fromisoformat(state["date"])
    if target_date < date.today():
        state.pop("date", None)
        conv.booking_state = state
        db.commit()
        return "Ngày bạn chọn đã qua mất rồi ạ. Bạn vui lòng chọn một ngày khác trong tương lai giúp tôi nhé."

    # Need proposed slots
    if not state.get("slot"):
        doctor, branch, slots = _pick_doctor_and_slots(db, conv.clinic_id, target_date, service.duration_minutes)
        if not slots:
            state["waitlist_offered"] = True
            state["waitlist_date"] = state.get("date")
            state.pop("date", None)
            state.pop("proposed_slots", None)
            conv.booking_state = state
            db.commit()
            return (f"Rất tiếc {_fmt_date_vn(target_date.isoformat())} các bác sĩ đã kín lịch hoặc không có ca làm việc. "
                    f"Bạn có thể chọn một ngày khác, hoặc nhắn 'chờ' để tôi đưa bạn vào danh sách chờ — "
                    f"có khách hủy lịch là tôi báo bạn ngay để nhận chỗ trước nhé!")
        state["doctor_id"] = doctor.id
        state["branch_id"] = branch.id if branch else None
        top = slots[:3]
        state["proposed_slots"] = top
        conv.booking_state = state
        db.commit()
        numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(top))
        return (f"Dạ, {_fmt_date_vn(state['date'])} bác sĩ {doctor.name} còn các khung giờ trống:\n{numbered}\n"
                f"Bạn vui lòng chọn một khung giờ (nhắn số 1/2/3 hoặc giờ cụ thể) nhé ạ.")

    # --- All info collected: create the appointment ---
    slot_h, slot_m = map(int, state["slot"].split(":"))
    start_dt = datetime.combine(target_date, datetime.min.time()).replace(hour=slot_h, minute=slot_m)
    end_dt = start_dt + timedelta(minutes=service.duration_minutes)

    # Sync lead identity
    if lead:
        if state.get("full_name") and not lead.full_name:
            lead.full_name = state["full_name"]
        if state.get("phone") and not lead.phone:
            lead.phone = state["phone"]

    # Attribution: booked after an automation follow-up in the last 7 days -> ai_followup
    recent_followup = db.query(ScheduledAction).filter(
        ScheduledAction.patient_id == conv.patient_id,
        ScheduledAction.status == "sent",
        ScheduledAction.executed_at != None,  # noqa: E711
        ScheduledAction.executed_at >= datetime.now() - timedelta(days=7)
    ).first()
    booking_source = "ai_followup" if recent_followup else "ai_chat"

    # Deposit policy of the clinic
    clinic = db.query(Clinic).filter(Clinic.id == conv.clinic_id).first() if conv.clinic_id else None
    deposit_amount = (clinic.deposit_amount or 0) if clinic else 0

    appt = Appointment(
        clinic_id=conv.clinic_id,
        patient_id=conv.patient_id,
        service_id=service.id,
        doctor_id=state["doctor_id"],
        branch_id=state.get("branch_id"),
        start_time=start_dt,
        end_time=end_dt,
        status="awaiting_deposit" if deposit_amount > 0 else "pending",
        booking_source=booking_source,
        conversation_id=conv.id,
        note=f"Đặt qua trợ lý AI (hội thoại #{conv.id})"
    )
    db.add(appt)
    db.flush()

    emit_event(db, conv.clinic_id, "appointment_created", patient_id=conv.patient_id,
               payload={"appointment_id": appt.id, "service_id": service.id,
                        "service_name": service.name, "source": booking_source})

    # Feed the booking back to Meta ads (CAPI) so campaigns optimize for real bookings
    try:
        from backend.app.services.capi import send_capi_event
        send_capi_event(db, conv.clinic_id, "Schedule", phone=state.get("phone"),
                        value=service.price, external_id=lead.external_id if lead else None)
    except Exception as e:
        print(f"[CAPI] skipped: {e}")

    conv.booking_state = {"active": False, "last_appointment_created": True}
    db.commit()

    doctor = db.query(Doctor).filter(Doctor.id == state["doctor_id"]).first()
    branch = db.query(Branch).filter(Branch.id == state.get("branch_id")).first()

    base_msg = (f"✅ Tôi đã đặt lịch hẹn thành công cho bạn:\n"
                f"- Họ tên: {state['full_name']} ({state['phone']})\n"
                f"- Dịch vụ: {service.name}\n"
                f"- Bác sĩ: {doctor.name if doctor else 'Sẽ được phân bổ'}\n"
                f"- Chi nhánh: {branch.name if branch else 'Trụ sở chính'}\n"
                f"- Thời gian: {state['slot']} {_fmt_date_vn(state['date'])}\n")

    if deposit_amount > 0:
        from backend.app.services.payment_gateway import create_deposit_payment, payment_url
        payment = create_deposit_payment(db, appt, deposit_amount)
        db.commit()
        return (base_msg +
                f"Để giữ chỗ chắc chắn, bạn vui lòng đặt cọc {deposit_amount:,.0f}đ "
                f"(sẽ được trừ vào hóa đơn) qua liên kết:\n{payment_url(payment)}\n"
                f"Lịch hẹn sẽ tự động XÁC NHẬN ngay khi thanh toán xong. Cảm ơn bạn!")

    return (base_msg +
            "Lịch hẹn đang ở trạng thái CHỜ XÁC NHẬN. Lễ tân sẽ liên hệ xác nhận với bạn sớm nhất. "
            "Cảm ơn bạn đã tin tưởng phòng khám!")
