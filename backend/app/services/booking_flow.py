"""
Rule-based booking-request state machine. It collects a patient's preferred
service/time and creates an administrative BookingRequest; only staff or a
calendar integration may create a confirmed Appointment.
"""
import re
from datetime import date, datetime, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session
from backend.app.models.models import (
    BookingRequest, Conversation, PatientLead, Service, Doctor, WorkingSchedule,
    Branch, WaitlistEntry
)
from backend.app.services.i18n import booking_text, locale_for_conversation, service_content
from backend.app.services.events import emit_event

BOOKING_INTENT_KEYWORDS = [
    "đặt lịch", "đặt hẹn", "book lịch", "muốn hẹn", "lịch hẹn", "đăng ký khám",
    "book an appointment", "make an appointment", "booking", "予約", "予約したい",
]
CANCEL_KEYWORDS = ["hủy đặt lịch", "không đặt nữa", "thôi không đặt", "hủy luôn", "cancel", "キャンセル"]
FAQ_KEYWORDS = [
    "giá", "bao nhiêu", "phí", "địa chỉ", "ở đâu", "mấy giờ", "mở cửa", "chi nhánh",
    "price", "cost", "address", "hours", "location", "料金", "住所", "営業時間",
]


def _say(locale: str, vi: str, en: str, ja: str) -> str:
    return {"vi": vi, "en": en, "ja": ja}.get(locale, en)

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
    if "ngày kia" in text_lower or "day after tomorrow" in text_lower or "明後日" in text_lower:
        return (today + timedelta(days=2)).isoformat()
    if "mai" in text_lower or "tomorrow" in text_lower or "明日" in text_lower:
        return (today + timedelta(days=1)).isoformat()
    if "hôm nay" in text_lower or "bữa nay" in text_lower or "today" in text_lower or "今日" in text_lower:
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
    m = re.search(r"\b(\d{1,2})\s*(?:h|giờ|am|pm|時)(?:\s*(\d{2}))?", text_lower)
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


def _resolve_service(db: Session, clinic_id: Optional[int], text_lower: str, locale: str = "vi") -> Optional[Service]:
    query = db.query(Service)
    if clinic_id:
        query = query.filter(Service.clinic_id == clinic_id)
    services = query.all()
    if not services:
        return None

        
    # Match legacy seed aliases first.
    for keywords, target_name in SERVICE_KEYWORD_MAP:
        if any(kw in text_lower for kw in keywords):
            for s in services:
                if s.name == target_name:
                    return s
            break

    # 2. Fuzzy match against both the legacy and requested localized service name.
    best, best_hits = None, 0
    for s in services:
        names = [s.name, service_content(s, locale)["name"]]
        hits = max(
            (sum(1 for w in name.lower().split() if len(w) > 2 and w in text_lower) for name in names),
            default=0,
        )
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


def _fmt_date(iso_date: str, locale: str) -> str:
    d = date.fromisoformat(iso_date)
    if locale == "ja":
        return f"{d.year}年{d.month}月{d.day}日"
    if locale == "en":
        return d.strftime("%A, %d %B %Y")
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
    locale = locale_for_conversation(conv, None)
    has_intent = any(kw in text_lower for kw in BOOKING_INTENT_KEYWORDS)

    if not state.get("active") and not has_intent:
        return None

    # Cancel the flow
    if state.get("active") and any(kw in text_lower for kw in CANCEL_KEYWORDS):
        conv.booking_state = {"active": False}
        db.commit()
        return _say(locale, "Dạ, tôi đã hủy yêu cầu đặt lịch. Nếu bạn cần hỗ trợ thêm, cứ nhắn cho tôi nhé!", "Your booking request has been cancelled. Please message me if you need further help.", "予約リクエストをキャンセルしました。ほかにお手伝いできることがあればお知らせください。")

    # Extract entities from this message
    new_service = _resolve_service(db, conv.clinic_id, text_lower, locale)
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
        listing = "\n".join(
            f"- {service_content(s, locale)['name']} ({s.price:,.0f}đ)" for s in query.all()
        )
        conv.booking_state = state
        db.commit()
        return _say(
            locale,
            f"Dạ, tôi rất sẵn lòng hỗ trợ bạn đặt lịch hẹn! Phòng khám hiện có các dịch vụ:\n{listing}\nBạn muốn đặt lịch dịch vụ nào ạ?",
            f"I can help with a booking request. The clinic offers:\n{listing}\nWhich service would you like?",
            f"予約リクエストをお手伝いします。ご利用いただけるサービス:\n{listing}\nご希望のサービスを教えてください。",
        )

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
            return (f"Rất tiếc {_fmt_date(target_date.isoformat(), locale)} các bác sĩ đã kín lịch hoặc không có ca làm việc. "
                    f"Bạn có thể chọn một ngày khác, hoặc nhắn 'chờ' để tôi đưa bạn vào danh sách chờ — "
                    f"có khách hủy lịch là tôi báo bạn ngay để nhận chỗ trước nhé!")
        state["doctor_id"] = doctor.id
        state["branch_id"] = branch.id if branch else None
        top = slots[:3]
        state["proposed_slots"] = top
        conv.booking_state = state
        db.commit()
        numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(top))
        return (f"Dạ, {_fmt_date(state['date'], locale)} bác sĩ {doctor.name} còn các khung giờ trống:\n{numbered}\n"
                f"Bạn vui lòng chọn một khung giờ (nhắn số 1/2/3 hoặc giờ cụ thể) nhé ạ.")

        
    # All details are present. A public chat never reserves inventory or creates an
    # appointment: it records only the patient's preference for staff confirmation.
    service_name = service_content(service, locale)["name"]
    preferred_time = f"{state['date']} {state['slot']}"
    request = BookingRequest(
        clinic_id=conv.clinic_id,
        conversation_id=conv.id,
        patient_id=conv.patient_id,
        service_id=service.id,
        locale=locale,
        service_or_need=service_name,
        preferred_time=preferred_time,
        full_name=state["full_name"],
        contact_method="phone",
        contact_value=state["phone"],
        note=_say(locale, f"Gửi từ hội thoại #{conv.id}", f"Submitted from conversation #{conv.id}", f"会話 #{conv.id} から送信"),
        )
    db.add(request)
    db.flush()

    emit_event(
        db, conv.clinic_id, "booking_request_created", patient_id=conv.patient_id,
        payload={"booking_request_id": request.id, "service_id": service.id, "service_name": service_name},
    )
    conv.booking_state = {"active": False, "last_booking_request_id": request.id}

    db.commit()

    summary = _say(
        locale,
        f"✅ Đã gửi yêu cầu đặt lịch:\n- Họ tên: {state['full_name']} ({state['phone']})\n- Dịch vụ: {service_name}\n- Thời gian mong muốn: {state['slot']} {_fmt_date(state['date'], locale)}\n",
        f"✅ Booking request sent:\n- Name: {state['full_name']} ({state['phone']})\n- Service: {service_name}\n- Preferred time: {state['slot']} {_fmt_date(state['date'], locale)}\n",
        f"✅ 予約リクエストを送信しました:\n- お名前: {state['full_name']} ({state['phone']})\n- サービス: {service_name}\n- 希望日時: {_fmt_date(state['date'], locale)} {state['slot']}\n",
    )
    return summary + booking_text(locale, "requested")
