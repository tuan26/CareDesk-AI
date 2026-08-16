"""
Rule-based booking-request state machine. It collects a patient's preferred
service/time and creates an administrative BookingRequest; only staff or a
calendar integration may create a confirmed Appointment.
"""
import re
import unicodedata
from datetime import date, datetime, time, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session
from backend.app.models.models import (
    BookingRequest, Conversation, PatientLead, Service, Doctor, WorkingSchedule,
    Branch, WaitlistEntry
)
from backend.app.services.i18n import booking_text, locale_for_conversation, service_content
from backend.app.services.events import emit_event
from backend.app.core import clock

def strip_accents(text: str) -> str:
    """Fold Vietnamese text to plain ASCII-ish lowercase for keyword matching.

    Vietnamese is very often typed without diacritics, and phones drop them
    silently. Matching accented literals meant "đặt lich" — one missing dot —
    never registered as booking intent, so the state machine stayed asleep and
    the model answered on its own. Both sides of every comparison are folded.

    "đ" has no combining form, so NFD leaves it intact and it needs its own rule.
    """
    decomposed = unicodedata.normalize("NFD", text or "")
    without_marks = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return without_marks.replace("đ", "d").replace("Đ", "D").lower()


_BOOKING_INTENT_SOURCE = [
    "đặt lịch", "đặt hẹn", "đặt khám", "book lịch", "muốn hẹn", "lịch hẹn",
    "đăng ký khám", "đăng ký lịch", "hẹn khám", "lấy lịch", "xếp lịch",
    "book an appointment", "make an appointment", "booking", "book me",
    "予約", "予約したい",
]
_CANCEL_SOURCE = [
    "hủy đặt lịch", "không đặt nữa", "thôi không đặt", "hủy luôn", "hủy lịch",
    "cancel", "キャンセル",
]

#: "Yes" to a question the assistant just asked.
#:
#: Deliberately excludes "có" and "dạ". They are the two most common words in a
#: Vietnamese question — "có đau không", "dạ cho em hỏi" — so counting them as
#: consent reads half of all questions as agreement, which is precisely how
#: "Làm xong có phải kiêng nắng không?" got answered with "ngày nào ạ?".
_AFFIRMATIVE = re.compile(
    r"\b(ok|oke|okie|okay|vang|dung roi|duoc|yes|sure|はい|お願い)\b"
)

#: An affirmative is a whole reply, not a word inside a sentence. "Được không
#: ạ, em hỏi thêm chút" contains "được" and agrees to nothing.
_AFFIRMATIVE_MAX_WORDS = 4

#: "When is she free?" — the natural next question after being told a doctor is
#: fully booked, and the one the assistant used to answer with "tôi không có
#: thông tin chi tiết về lịch trống" while the schedule sat in the database.
_WHEN_FREE = re.compile(
    r"(ngay nao|hom nao|khi nao|lich trong|con trong|con lich|lich lam viec|"
    r"ranh ngay|lam viec ngay|which days?|when.*(free|available))"
)

#: How far ahead "trống ngày nào" looks. Two weeks covers "tuần sau" and the
#: window nearly every aesthetics booking falls in.
_FREE_DAYS_HORIZON = 14

#: "Whoever is free." Pinning a doctor has to be undoable, or a patient told
#: their choice is fully booked has no way to say yes to the alternative and
#: sits in the same question for ever.
_ANY_DOCTOR = re.compile(
    r"(bac si khac|bs khac|bac si nao cung|ai cung duoc|sao cung duoc|"
    r"tuy phong kham|tuy benh vien|nguoi khac|another doctor|any doctor|anyone)"
)


def _doctor_label(name: str) -> str:
    """"bác sĩ {name}" reads as "bác sĩ Bác sĩ Nguyễn Văn A" whenever the clinic
    typed the title into the name field — which most of them do."""
    return name if strip_accents(name).startswith(("bac si", "bs", "ts", "pgs")) \
        else f"bác sĩ {name}"


def _is_affirmative(text_folded: str) -> bool:
    return (len(text_folded.split()) <= _AFFIRMATIVE_MAX_WORDS
            and bool(_AFFIRMATIVE.search(text_folded)))

# Folded once at import; user text is folded per message.
BOOKING_INTENT_KEYWORDS = [strip_accents(k) for k in _BOOKING_INTENT_SOURCE]
CANCEL_KEYWORDS = [strip_accents(k) for k in _CANCEL_SOURCE]

# FAQ_KEYWORDS used to decide which mid-flow questions deserved a real answer.
# It was the wrong test — it only listed price and address wording, so "có đau
# không" and "bao lâu thì khỏi" were treated as booking input. Absence of
# booking data replaced it; see handle_booking.


from backend.app.services.i18n import say as _say

SERVICE_KEYWORD_MAP = [
    (["nặn mụn", "trị mụn", "mụn"], "Điều trị mụn Chuẩn Y Khoa"),
    (["laser", "sẹo", "co2"], "Laser Fractional CO2 trị sẹo rỗ"),
    # "bác sĩ" used to sit in this row. It is not a service word — it is how
    # every question about the team starts. "Có những bác sĩ nào?" resolved to
    # the consultation service, counted as the patient choosing it, and got
    # answered with a list of free slots.
    (["khám", "soi da"], "Khám da liễu với Bác sĩ chuyên khoa"),
]

WEEKDAY_PATTERNS = [
    (r"thứ\s*2|thu\s*2", 0), (r"thứ\s*3|thu\s*3", 1), (r"thứ\s*4|thu\s*4", 2),
    (r"thứ\s*5|thu\s*5", 3), (r"thứ\s*6|thu\s*6", 4), (r"thứ\s*7|thu\s*7", 5),
    (r"chủ\s*nhật|chu\s*nhat|\bcn\b", 6),
]


def _parse_date(text_lower: str) -> Optional[str]:
    """Parse a target date from Vietnamese text. Returns ISO date string."""
    today = clock.today()
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

        
    # Accent-folded on both sides: a patient typing "tri mun" or "seo ro" is
    # naming the same service as one who types it with diacritics.
    folded = strip_accents(text_lower)

    # Match legacy seed aliases first.
    for keywords, target_name in SERVICE_KEYWORD_MAP:
        if any(strip_accents(kw) in folded for kw in keywords):
            for s in services:
                if s.name == target_name:
                    return s
            break

    # 2. Fuzzy match against both the legacy and requested localized service name.
    best, best_hits = None, 0
    for s in services:
        names = [s.name, service_content(s, locale)["name"]]
        hits = max(
            (sum(1 for w in strip_accents(name).split() if len(w) > 2 and w in folded)
             for name in names),
            default=0,
        )
        if hits > best_hits:
            best, best_hits = s, hits
    return best if best_hits >= 2 else None


def _branch_ever_open(db: Session, branch_id: int) -> bool:
    """Does this location have any working schedule at all?"""
    return db.query(WorkingSchedule).filter(
        WorkingSchedule.branch_id == branch_id
    ).first() is not None


def _other_open_branches(db: Session, clinic_id: Optional[int], exclude_id: int) -> list:
    """Sibling locations that can actually take a booking."""
    query = db.query(Branch).filter(Branch.id != exclude_id, Branch.is_active == True)  # noqa: E712
    if clinic_id:
        query = query.filter(Branch.clinic_id == clinic_id)
    return [b for b in query.all() if _branch_ever_open(db, b.id)]


def open_slots(db: Session, clinic_id: Optional[int], target_date: date,
               duration: int, branch_id: Optional[int] = None,
               doctor_id: Optional[int] = None) -> list:
    """Every free slot at a location on a date, as (time, doctor) pairs.

    The chat flow only ever needs the first doctor who can take the booking, but
    a form has to show the patient everything they could pick — including the
    same time offered by two different doctors.

    Sorted by time: a patient scanning for "chiều thứ 5" reads the clock, not the
    staff list.
    """
    from backend.app.services.ai_engine import get_available_slots

    query = db.query(Doctor).filter(Doctor.is_active == True)  # noqa: E712
    if clinic_id:
        query = query.filter(Doctor.clinic_id == clinic_id)
    if doctor_id:
        query = query.filter(Doctor.id == doctor_id)

    weekday = target_date.weekday()
    out = []
    for doctor in query.all():
        schedules = db.query(WorkingSchedule).filter(
            WorkingSchedule.doctor_id == doctor.id,
            WorkingSchedule.day_of_week == weekday,
        )
        if branch_id:
            schedules = schedules.filter(WorkingSchedule.branch_id == branch_id)
        if not schedules.first():
            continue
        for slot in get_available_slots(db, doctor.id, target_date, duration):
            out.append((slot, doctor))

    out.sort(key=lambda pair: pair[0])
    return out


def days_with_availability(db: Session, clinic_id: Optional[int], start: date,
                           count: int, duration: int,
                           branch_id: Optional[int] = None,
                           doctor_id: Optional[int] = None) -> list:
    """(date, free slot count) for the next `count` days.

    So the day picker can say which days are worth choosing instead of listing
    fourteen identical buttons and letting the patient find the closed ones by
    trial and error. A picker that cannot tell Sunday from a fully booked
    Tuesday is a list, not a choice.

    Deliberately built by calling open_slots per day rather than by a faster
    bulk query: the picker and the slot list must never disagree. A grid that
    promises a free Thursday and a step 4 that shows nothing is worse than no
    grid at all — and any second implementation of "is this slot free" would
    drift from the first within a release or two.
    """
    return [
        (start + timedelta(days=offset),
         len(open_slots(db, clinic_id, start + timedelta(days=offset), duration,
                        branch_id=branch_id, doctor_id=doctor_id)))
        for offset in range(count)
    ]


def _resolve_service_by_id(db: Session, service_id: Optional[int]) -> Optional[Service]:
    return db.query(Service).filter(Service.id == service_id).first() if service_id else None


def _resolve_doctor(db: Session, clinic_id: Optional[int], text: str) -> Optional[Doctor]:
    """Which doctor the patient named, if any.

    Matched on the full name, accent-folded on both sides so "bac si le thi b"
    finds "Bác sĩ Lê Thị B". Deliberately not on single tokens: half the doctors
    in a Vietnamese clinic share a surname, and "chị B" is not enough to book
    someone's afternoon on.
    """
    query = db.query(Doctor).filter(Doctor.is_active == True)  # noqa: E712
    if clinic_id:
        query = query.filter(Doctor.clinic_id == clinic_id)

    folded = strip_accents(text)
    best = None
    for doctor in query.all():
        name = strip_accents(doctor.name)
        # Also try without the title, so "Lê Thị B" matches "Bác sĩ Lê Thị B".
        bare = re.sub(r"^(bac si|bs\.?|ts\.?|pgs\.?|ths\.?)\s+", "", name).strip()
        for candidate in (name, bare):
            if len(candidate) >= 4 and candidate in folded:
                # Longest match wins: "Le Thi B" must not lose to a shorter name
                # that happens to be a substring of it.
                if best is None or len(candidate) > best[1]:
                    best = (doctor, len(candidate))
    return best[0] if best else None


def _pick_doctor_and_slots(db: Session, clinic_id: Optional[int], target_date: date,
                           duration: int, branch_id: Optional[int] = None,
                           doctor_id: Optional[int] = None):
    """Find an active doctor with free slots on the date. Returns (doctor, branch, slots).

    `branch_id` pins the search to the location the patient actually chose. Left
    unset this scans every doctor in the clinic and returns the first with a free
    slot, which is why a patient who clicked "Cơ sở Bạch Mai" used to be booked
    into whatever branch the first available doctor worked at.

    `doctor_id` does the same for the person. A patient who asks for Bác sĩ B and
    is quietly given Bác sĩ A finds out in the waiting room, and the clinic finds
    out from the complaint. When the requested doctor has nothing free this
    returns no slots rather than substituting someone else — the caller says so.
    """
    from backend.app.services.ai_engine import get_available_slots

    weekday = target_date.weekday()
    query = db.query(Doctor).filter(Doctor.is_active == True)  # noqa: E712
    if clinic_id:
        query = query.filter(Doctor.clinic_id == clinic_id)
    if doctor_id:
        query = query.filter(Doctor.id == doctor_id)
    for doctor in query.all():
        schedules = db.query(WorkingSchedule).filter(
            WorkingSchedule.doctor_id == doctor.id,
            WorkingSchedule.day_of_week == weekday
        )
        if branch_id:
            # A doctor may work different days at different branches, so filter
            # the schedule too rather than trusting doctor.branch_id alone.
            schedules = schedules.filter(WorkingSchedule.branch_id == branch_id)
        has_schedule = schedules.first()
        if not has_schedule:
            continue
        slots = get_available_slots(db, doctor.id, target_date, duration)
        if slots:
            resolved = branch_id or doctor.branch_id or has_schedule.branch_id
            branch = db.query(Branch).filter(Branch.id == resolved).first()
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


def _fmt_slot(when: datetime, locale: str) -> str:
    """One reading of a requested time across every entry point.

    The chat wrote "2026-08-16 18:00" and the web form wrote "10:30 16/08/2026
    — Chi nhánh Quận 10", in the same column, in the same list. A receptionist
    scanning that column had to switch formats between rows.
    """
    if locale == "ja":
        return when.strftime("%Y年%m月%d日 %H:%M")
    if locale == "en":
        return when.strftime("%H:%M %d %b %Y")
    return when.strftime("%H:%M %d/%m/%Y")


def handle_booking(db: Session, conv: Conversation, user_message: str) -> Optional[str]:
    """
    Advance the booking state machine with a new patient message.
    Returns the bot response text, or None if this message is not booking-related
    (caller falls through to FAQ / LLM handling).
    """
    state = dict(conv.booking_state or {})
    text_lower = user_message.lower()
    # Keyword matching runs on the accent-folded form; the parsers below keep the
    # original because their patterns already spell out both variants.
    text_folded = strip_accents(user_message)
    locale = locale_for_conversation(conv, None)
    has_intent = any(kw in text_folded for kw in BOOKING_INTENT_KEYWORDS)

    if not state.get("active") and not has_intent:
        return None

    # Cancel the flow
    if state.get("active") and any(kw in text_folded for kw in CANCEL_KEYWORDS):
        conv.booking_state = {"active": False}
        db.commit()
        return _say(locale, "Dạ, tôi đã hủy yêu cầu đặt lịch. Nếu bạn cần hỗ trợ thêm, cứ nhắn cho tôi nhé!", "Your booking request has been cancelled. Please message me if you need further help.", "予約リクエストをキャンセルしました。ほかにお手伝いできることがあればお知らせください。")

    # Extract entities from this message
    new_service = _resolve_service(db, conv.clinic_id, text_lower, locale)
    new_doctor = _resolve_doctor(db, conv.clinic_id, user_message)
    releases_doctor = bool(state.get("doctor_requested")) and bool(_ANY_DOCTOR.search(text_folded))
    new_date = _parse_date(text_lower)
    new_time = _parse_time(text_lower)
    new_phone = _parse_phone(user_message)
    new_name = _parse_name(user_message)

    # A message that carries no booking information is not advancing the
    # booking, whatever else it is — so the assistant should answer it instead of
    # replying with the next form field.
    #
    # This used to require a word from FAQ_KEYWORDS, which meant "Laser CO2 có
    # đau không?" and "bao lâu thì hết mụn?" were swallowed by the state machine
    # and answered with "bạn muốn khám ngày nào ạ?". Absence of booking data is
    # the reliable signal; a list of question words never will be.
    #
    # Only once the flow has actually collected something. On the turn it is
    # first activated there is nothing to fall back to, and bailing out would
    # leave the patient with whatever the model happened to say and no question
    # to answer.
    # "Bác sĩ B tuần sau trống ngày nào?" — answerable from the schedule, and
    # answered until now with "tôi không có thông tin chi tiết về lịch trống"
    # followed by a handoff. The rota is in the database; not offering it sent
    # the patient to a receptionist to read out something the product knows.
    asked_about = new_doctor or (
        db.query(Doctor).filter(Doctor.id == state["doctor_id"]).first()
        if state.get("doctor_id") else None)
    if asked_about and _WHEN_FREE.search(text_folded):
        service_for_days = _resolve_service_by_id(db, state.get("service_id"))
        duration = service_for_days.duration_minutes if service_for_days else 30
        free = [(day, count) for day, count in days_with_availability(
            db, conv.clinic_id, clock.today(), _FREE_DAYS_HORIZON, duration,
            branch_id=conv.branch_id, doctor_id=asked_about.id) if count]
        conv.booking_state = state
        db.commit()
        label = _doctor_label(asked_about.name)
        if not free:
            return (f"Trong 2 tuần tới {label} chưa có lịch trống ạ. "
                    f"Bạn muốn để tôi xếp bác sĩ khác cùng chuyên môn không ạ?")
        listed = ", ".join(_fmt_date(day.isoformat(), locale) for day, _ in free[:6])
        return (f"Dạ, {label} còn lịch các ngày: {listed}.\n"
                f"Bạn chọn ngày nào ạ?")

    mid_flow = any(state.get(k) for k in
                   ("service_id", "date", "slot", "proposed_slots", "full_name", "phone"))
    # Naming the service already chosen adds nothing — "Laser CO2 có đau không?"
    # is a question about the booking in progress, not an answer to it. Only a
    # *different* service is new information.
    adds_new = bool(new_date or new_time or new_phone or new_name or releases_doctor
                    or (new_service and new_service.id != state.get("service_id"))
                    or (new_doctor and new_doctor.id != state.get("doctor_id")))
    if state.get("active") and mid_flow and not has_intent and not adds_new \
            and not _is_affirmative(text_folded) \
            and not (state.get("proposed_slots") and re.fullmatch(r"\s*\d\s*\.?\s*", user_message)):
        return None

    if not state.get("active"):
        state = {"active": True}

    if new_service:
        state["service_id"] = new_service.id
    if releases_doctor:
        # "bác sĩ khác cũng được" — the only way out of a pinned doctor whose
        # diary is full. Without it the assistant asks the same question for
        # ever, because the answer it offered had no handler.
        state.pop("doctor_id", None)
        state.pop("doctor_requested", None)
        state.pop("proposed_slots", None)
        state.pop("slot", None)
    elif new_doctor and new_doctor.id != state.get("doctor_id"):
        # Naming a doctor re-opens the times: the ones already quoted were
        # somebody else's.
        state["doctor_id"] = new_doctor.id
        state["doctor_requested"] = True
        state.pop("proposed_slots", None)
        state.pop("slot", None)
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
        # Not "đã ghi nhận": nothing is saved until every field is in and the
        # BookingRequest is written. A patient told their booking is recorded
        # stops answering, and the request dies half-collected.
        return (f"Dạ, để đặt lịch dịch vụ {service.name}, "
                f"bạn cho tôi xin: {', '.join(missing)} nhé ạ.")

    if not state.get("date"):
        conv.booking_state = state
        db.commit()
        # Echo the doctor back when the patient named one, so they can see it
        # landed rather than discovering in the waiting room that it did not.
        chosen = db.query(Doctor).filter(Doctor.id == state["doctor_id"]).first() \
            if state.get("doctor_requested") and state.get("doctor_id") else None
        with_doctor = f"- Bác sĩ: {chosen.name}\n" if chosen else ""
        return (f"Dạ, tôi đang chuẩn bị yêu cầu đặt lịch cho bạn:\n"
                f"- Họ tên: {state['full_name']}\n"
                f"- Số điện thoại: {state['phone']}\n"
                f"- Dịch vụ: {service.name}\n"
                f"{with_doctor}"
                f"Bạn muốn khám vào ngày nào ạ? (ví dụ: ngày mai, thứ 7, hoặc 25/07)")

    target_date = date.fromisoformat(state["date"])
    if target_date < clock.today():
        state.pop("date", None)
        conv.booking_state = state
        db.commit()
        return "Ngày bạn chọn đã qua mất rồi ạ. Bạn vui lòng chọn một ngày khác trong tương lai giúp tôi nhé."

    # Need proposed slots
    if not state.get("slot"):
        requested_doctor_id = state.get("doctor_id") if state.get("doctor_requested") else None
        doctor, branch, slots = _pick_doctor_and_slots(
            db, conv.clinic_id, target_date, service.duration_minutes,
            branch_id=conv.branch_id,  # honour the location the patient arrived from
            doctor_id=requested_doctor_id,   # and the person they asked for
        )

        # The doctor they asked for is not free that day. Say whose diary is
        # full and let them choose — substituting a colleague silently is how a
        # patient ends up in front of someone they did not pick.
        if not slots and requested_doctor_id:
            named = db.query(Doctor).filter(Doctor.id == requested_doctor_id).first()
            _, _, any_slots = _pick_doctor_and_slots(
                db, conv.clinic_id, target_date, service.duration_minutes,
                branch_id=conv.branch_id)
            state.pop("proposed_slots", None)
            conv.booking_state = state
            db.commit()
            label = _doctor_label(named.name) if named else "bác sĩ bạn chọn"
            when = _fmt_date(target_date.isoformat(), locale)
            if any_slots:
                return (f"Rất tiếc {when} {label} đã kín lịch ạ. "
                        f"Bạn muốn chọn ngày khác với {label}, "
                        f"hay để tôi xếp bác sĩ khác cũng chuyên môn này ạ?")
            return (f"Rất tiếc {when} {label} không có ca làm việc ạ. "
                    f"Bạn cho tôi xin một ngày khác nhé?")

        if not slots and conv.branch_id and not _branch_ever_open(db, conv.branch_id):
            # The pinned location has no working schedule at all, so no date will
            # ever produce a slot. Say so and unpin, instead of looping the
            # patient through "fully booked" forever.
            other = _other_open_branches(db, conv.clinic_id, conv.branch_id)
            conv.branch_id = None
            state.pop("date", None)
            state.pop("proposed_slots", None)
            conv.booking_state = state
            db.commit()
            if other:
                names = ", ".join(b.name for b in other)
                return (f"Cơ sở bạn chọn hiện chưa mở lịch khám trực tuyến ạ. "
                        f"Các cơ sở đang nhận lịch: {names}. "
                        f"Bạn muốn đặt tại cơ sở nào ạ?")
            return ("Hiện phòng khám chưa mở lịch khám trực tuyến cho cơ sở này ạ. "
                    "Bạn vui lòng để lại số điện thoại, lễ tân sẽ gọi lại sắp xếp giúp bạn nhé.")

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
        return (f"Dạ, {_fmt_date(state['date'], locale)} {_doctor_label(doctor.name)} còn các khung giờ trống:\n{numbered}\n"
                f"Bạn vui lòng chọn một khung giờ (nhắn số 1/2/3 hoặc giờ cụ thể) nhé ạ.")

        
    # All details are present. A public chat never reserves inventory or creates an
    # appointment: it records only the patient's preference for staff confirmation.
    service_name = service_content(service, locale)["name"]
    # The chat already knows both — it pinned the branch when the patient arrived
    # and named the doctor when it quoted times. Dropping them left reception
    # with a request that said neither.
    branch_id = state.get("branch_id") or conv.branch_id
    doctor_id = state.get("doctor_id")
    preferred_at = datetime.combine(date.fromisoformat(state["date"]),
                                    time.fromisoformat(state["slot"]))
    preferred_time = _fmt_slot(preferred_at, locale)
    request = BookingRequest(
        clinic_id=conv.clinic_id,
        conversation_id=conv.id,
        patient_id=conv.patient_id,
        service_id=service.id,
        branch_id=branch_id,
        doctor_id=doctor_id,
        locale=locale,
        service_or_need=service_name,
        preferred_at=preferred_at,
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
