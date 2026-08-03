import json
import re
from datetime import datetime, date, time, timedelta
from typing import Dict, Any, List, Tuple, Optional
from sqlalchemy.orm import Session
from backend.app.core.config import settings
from backend.app.models.models import (
    Conversation, Message, PatientLead, Service, Doctor, WorkingSchedule, Appointment, AISafetyRule,
    Clinic, Branch
)
from backend.app.services.i18n import locale_for_conversation, normalize_locale, service_content

# Initialize OpenAI client if API key is provided
openai_client = None
if settings.OPENAI_API_KEY:
    try:
        from openai import OpenAI
        openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
    except Exception as e:
        print(f"Failed to initialize OpenAI client: {e}")


def check_safety_rules(db: Session, text: str, clinic_id: Optional[int] = None) -> Optional[AISafetyRule]:
    """
    Check if the text contains any dangerous keywords defined in AISafetyRule.
    Global rules (clinic_id NULL) always apply; clinic-specific rules apply on top.
    Returns the matched AISafetyRule or None.
    """
    query = db.query(AISafetyRule)
    if clinic_id:
        query = query.filter((AISafetyRule.clinic_id == None) | (AISafetyRule.clinic_id == clinic_id))  # noqa: E711
    rules = query.all()
    text_lower = text.lower()
    
    for rule in rules:
        keywords = [kw.strip().lower() for kw in rule.keyword_pattern.split(",") if kw.strip()]
        for kw in keywords:
            # Simple keyword search (can be upgraded to regex match)
            if kw in text_lower:
                return rule
    return None


def get_available_slots(db: Session, doctor_id: int, target_date: date, duration_minutes: int) -> List[time]:
    """
    Find available time slots for a doctor on a specific date based on working schedules and appointments.
    """
    # 1. Get doctor's schedule for this day of week
    day_of_week = target_date.weekday()  # 0 = Monday, 6 = Sunday
    schedules = db.query(WorkingSchedule).filter(
        WorkingSchedule.doctor_id == doctor_id,
        WorkingSchedule.day_of_week == day_of_week
    ).all()
    
    if not schedules:
        return []
        
    # 2. Get existing appointments for this doctor on this day
    start_of_day = datetime.combine(target_date, time.min)
    end_of_day = datetime.combine(target_date, time.max)
    
    existing_appointments = db.query(Appointment).filter(
        Appointment.doctor_id == doctor_id,
        Appointment.start_time >= start_of_day,
        Appointment.start_time <= end_of_day,
        Appointment.status.in_(["pending", "confirmed"])
    ).all()
    
    # 3. Generate all slots of `duration_minutes` within working hours
    all_slots = []
    for sched in schedules:
        current_time = datetime.combine(target_date, sched.start_time)
        end_work_time = datetime.combine(target_date, sched.end_time)
        
        while current_time + timedelta(minutes=duration_minutes) <= end_work_time:
            slot_start = current_time
            slot_end = current_time + timedelta(minutes=duration_minutes)
            
            # Check overlap with existing appointments
            overlap = False
            for appt in existing_appointments:
                # Appt overlap condition: Max(start1, start2) < Min(end1, end2)
                # Ensure we handle tz-naive vs tz-aware comparisons by making both naive for comparison
                appt_start = appt.start_time.replace(tzinfo=None)
                appt_end = appt.end_time.replace(tzinfo=None)
                
                if max(slot_start, appt_start) < min(slot_end, appt_end):
                    overlap = True
                    break
                    
            # Check if slot is in the past (only for today)
            if target_date == date.today() and slot_start < datetime.now():
                overlap = True
                
            if not overlap:
                all_slots.append(slot_start.time())
                
            current_time += timedelta(minutes=30)  # Increment slot by 30 mins
            
    return all_slots


def resolve_clinic(db: Session, clinic_id: Optional[int]) -> Optional[Clinic]:
    """
    Resolve the tenant for this conversation. If clinic_id is missing (legacy
    single-tenant data), fall back to the only clinic ONLY when exactly one
    exists — never leak data across tenants when several are present.
    """
    if clinic_id:
        return db.query(Clinic).filter(Clinic.id == clinic_id).first()
    clinics = db.query(Clinic).limit(2).all()
    return clinics[0] if len(clinics) == 1 else None


def clinic_services(db: Session, clinic: Optional[Clinic]) -> List[Service]:
    if not clinic:
        return []
    return db.query(Service).filter(Service.clinic_id == clinic.id).all()


def build_clinic_identity(db: Session, clinic: Optional[Clinic],
                          branch_id: Optional[int] = None) -> str:
    """One identity block (name/address/hotline + branches), strictly clinic-scoped.

    When the patient arrived from a specific location, say so up front: otherwise
    the model answers "địa chỉ ở đâu" by listing every branch, which is the wrong
    answer for someone who already picked one.
    """
    if not clinic:
        return "Thông tin phòng khám chưa được cấu hình."
    lines = [f"Tên phòng khám: {clinic.name}."]
    if clinic.address:
        lines.append(f"Địa chỉ: {clinic.address}.")
    if clinic.phone:
        lines.append(f"Hotline: {clinic.phone}.")

    chosen = None
    if branch_id:
        chosen = db.query(Branch).filter(
            Branch.id == branch_id, Branch.clinic_id == clinic.id).first()
    if chosen:
        hours = f" — giờ làm việc {chosen.working_hours}" if chosen.working_hours else ""
        phone = f" — điện thoại {chosen.phone}" if chosen.phone else ""
        lines.append(
            f"KHÁCH ĐANG HỎI VỀ CƠ SỞ: {chosen.name}: {chosen.address}{hours}{phone}. "
            f"Hãy trả lời theo cơ sở này và đặt lịch tại đây, trừ khi khách đổi sang cơ sở khác."
        )

    branches = db.query(Branch).filter(
        Branch.clinic_id == clinic.id, Branch.is_active == True).all()  # noqa: E712
    others = [b for b in branches if not chosen or b.id != chosen.id]
    if others:
        lines.append("Các cơ sở khác:" if chosen else "Các cơ sở:")
        for b in others:
            hours = f" — giờ làm việc {b.working_hours}" if b.working_hours else ""
            lines.append(f"- {b.name}: {b.address}{hours}.")
    return "\n".join(lines)


def query_faq_rag(db: Session, query: str, clinic_id: Optional[int] = None, locale: str = "vi",
                  branch_id: Optional[int] = None) -> str:
    """
    Simple RAG implementation, STRICTLY scoped to one clinic: matches query
    keywords against THIS clinic's services + FAQ. Never reads other tenants' data.
    """
    clinic = resolve_clinic(db, clinic_id)
    services = clinic_services(db, clinic)

    # Always give the model the clinic identity (name/address/branch hours) so it
    # can reliably answer "địa chỉ / mấy giờ" even when the query also hits a service.
    context_chunks = [build_clinic_identity(db, clinic, branch_id)]  # clinic identity
    matched_chunks = []

    query_lower = query.lower()
    locale = normalize_locale(locale)
    for service in services:
        content = service_content(service, locale)
        names = (service.name, content["name"])
        matched = any(name and name.lower() in query_lower for name in names)
        if not matched:
            matched = any(
                len(word) > 2 and word in query_lower
                for name in names for word in name.lower().split()
            )

        if matched:
            chunk = f"Service: {content['name']}. Price: {service.price:,.0f} VND. Duration: {service.duration_minutes} minutes. Description: {content['description']}."
            if content["preparation_instructions"]:
                chunk += f" Preparation: {content['preparation_instructions']}"
            matched_chunks.append(chunk)
            for faq in content["faq"]:
                if isinstance(faq, dict) and faq.get("question") and faq.get("answer"):
                    matched_chunks.append(f"Q: {faq['question']} -> A: {faq['answer']}")

    if matched_chunks:
        context_chunks.extend(matched_chunks)
    else:
        # No specific service matched: list this clinic's full catalogue briefly
        for service in services:
            content = service_content(service, locale)
            context_chunks.append(f"- Service {content['name']}: price {service.price:,.0f} VND (duration: {service.duration_minutes} minutes).")

    return "\n".join(context_chunks)


def extract_booking_entities_mock(text: str) -> Dict[str, Any]:
    """
    Mock entity extraction using simple regex rules.
    Used when OpenAI is not available.
    """
    entities = {
        "full_name": None,
        "phone": None,
        "service_name": None,
        "date_str": None,
        "time_str": None
    }
    
    # Extract phone number
    phone_match = re.search(r'(0[3|5|7|8|9]\d{8})\b', text)
    if phone_match:
        entities["phone"] = phone_match.group(1)
        
    # Extract name (e.g. "tên tôi là Nguyễn Văn A", "mình là Linh", "tên là Huy")
    name_match = re.search(r'(?:tên tôi là|tên là|mình là|xưng là|tên|gọi tôi là)\s+([A-ZÀ-Ỹa-zà-ỹ\s]{2,20})', text, re.IGNORECASE)
    if name_match:
        entities["full_name"] = name_match.group(1).strip()
        
    # Extract service keywords
    text_lower = text.lower()
    if "khám" in text_lower or "soi da" in text_lower or "bác sĩ" in text_lower:
        entities["service_name"] = "Khám da liễu với Bác sĩ chuyên khoa"
    elif "mụn" in text_lower or "nặn mụn" in text_lower or "trị mụn" in text_lower:
        entities["service_name"] = "Điều trị mụn Chuẩn Y Khoa"
    elif "laser" in text_lower or "sẹo" in text_lower or "co2" in text_lower:
        entities["service_name"] = "Laser Fractional CO2 trị sẹo rỗ"
        
    # Extract time/date (very simple mock)
    if "mai" in text_lower:
        entities["date_str"] = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    elif "thứ 7" in text_lower or "thu 7" in text_lower:
        # Find next Saturday
        today = date.today()
        days_ahead = 5 - today.weekday()
        if days_ahead <= 0: # Already Saturday or Sunday
            days_ahead += 7
        entities["date_str"] = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    elif "hôm nay" in text_lower:
        entities["date_str"] = date.today().strftime("%Y-%m-%d")
        
    # Time match (e.g. "8h", "9 giờ", "14:30")
    time_match = re.search(r'(\d{1,2})(?:\s*h|\s*giờ)(?:\s*(\d{2}))?', text_lower)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        entities["time_str"] = f"{hour:02d}:{minute:02d}"
        
    return entities


def call_openai_gpt_mock(db: Session, clinic: Optional[Clinic], user_query: str, locale: str = "vi") -> str:
    """
    Fallback AI response when no OpenAI key is set. Data-driven from THIS clinic's
    own catalogue/branches — no hardcoded clinic name, price or address, so it is
        correct for every tenant (not just the CareDesk demo).
    """
    query_lower = user_query.lower()
    locale = normalize_locale(locale)
    services = clinic_services(db, clinic)
    clinic_name = clinic.name if clinic else "clinic"

    def _match_service(q: str) -> Optional[Service]:
        # Rank by number of matching name-words so a specific hit ("trị mụn")
                # beats an incidental one ("phòng khám" -> "Khám da liễu").
        best, best_hits = None, 0
        for s in services:
            names = (s.name, service_content(s, locale)["name"])
            if any(name.lower() in q for name in names):
                return s
            hits = max(sum(1 for w in name.lower().split() if len(w) > 2 and w in q) for name in names)
            if hits > best_hits:
                best, best_hits = s, hits
        return best if best_hits >= 1 else None

        
    
        # 1. Pricing
    if any(k in query_lower for k in ("giá", "bao nhiêu", "phí", "price", "cost", "料金")):
        s = _match_service(query_lower)
        if s:
            name = service_content(s, locale)["name"]
            if locale == "en":
                return f"{name} at {clinic_name} costs {s.price:,.0f} VND and takes {s.duration_minutes} minutes. Would you like to make a booking request?"
            if locale == "ja":
                return f"{clinic_name}の{name}は{s.price:,.0f} VND、所要時間は{s.duration_minutes}分です。予約リクエストをご希望ですか？"
            return f"Dạ, dịch vụ {name} tại {clinic_name} có giá {s.price:,.0f}đ cho {s.duration_minutes} phút. Bạn có muốn gửi yêu cầu đặt lịch không ạ?"
        if services:
            listing = "; ".join(f"{s.name} ({s.price:,.0f}đ)" for s in services[:6])
            return f"Dạ, {clinic_name} hiện có các dịch vụ: {listing}. Bạn đang quan tâm dịch vụ nào ạ?"
        return f"Dạ, bạn vui lòng để lại thông tin, lễ tân {clinic_name} sẽ báo giá chi tiết cho bạn nhé."

    # 2. Address / branches
    if any(k in query_lower for k in ("địa chỉ", "ở đâu", "chi nhánh")):
        branches = db.query(Branch).filter(Branch.clinic_id == clinic.id).all() if clinic else []
        if branches:
            lines = "\n".join(
                f"- {b.name}: {b.address}" + (f" ({b.working_hours})" if b.working_hours else "")
                for b in branches
            )
            return f"Dạ, {clinic_name} có các cơ sở sau:\n{lines}\nBạn ở gần khu vực nào hơn ạ?"
        if clinic and clinic.address:
            return f"Dạ, {clinic_name} ở địa chỉ: {clinic.address}. Bạn cần tôi chỉ đường chi tiết không ạ?"
        return f"Dạ, bạn vui lòng để lại thông tin, lễ tân {clinic_name} sẽ gửi địa chỉ cho bạn nhé."

    # 3. Working hours
    if any(k in query_lower for k in ("giờ làm", "mở cửa", "mấy giờ")):
        branches = db.query(Branch).filter(Branch.clinic_id == clinic.id).all() if clinic else []
        opened = [b for b in branches if b.working_hours]
        if opened:
            lines = "\n".join(f"- {b.name}: {b.working_hours}" for b in opened)
            return f"Dạ, giờ làm việc của {clinic_name}:\n{lines}"
        return f"Dạ, bạn vui lòng liên hệ hotline để biết giờ làm việc của {clinic_name} nhé."

    # 4. Booking hint (the real end-to-end flow is handled by booking_flow)
    if any(k in query_lower for k in ("đặt lịch", "hẹn", "book", "khám")):
        names = ", ".join(s.name for s in services[:4]) if services else "dịch vụ bạn cần"
        return (f"Dạ, tôi có thể giúp bạn đặt lịch tại {clinic_name}. "
                f"Bạn muốn đặt dịch vụ nào ({names})? Cho tôi xin họ tên và số điện thoại để đăng ký nhé ạ.")

    return (f"Chào bạn, tôi là trợ lý ảo của {clinic_name}. Tôi có thể giúp bạn tra bảng giá dịch vụ, "
            f"địa chỉ, giờ làm việc và đặt lịch hẹn nhanh chóng. Bạn cần tôi hỗ trợ thông tin gì ạ?")


def handle_review_reply(db: Session, conv: Conversation, user_message: str) -> Optional[str]:
    """
    If this patient has a pending review request, interpret the message as a 1-5 rating.
    4-5 stars -> thank + Google review link + referral voucher code.
    1-3 stars -> intercepted: escalate to the owner BEFORE it becomes a public bad review.
    """
    import random
    import string
    from backend.app.models.models import ReviewRequest

    review = db.query(ReviewRequest).filter(
        ReviewRequest.patient_id == conv.patient_id,
        ReviewRequest.status == "pending"
    ).order_by(ReviewRequest.sent_at.desc()).first()
    if not review:
        return None

    m = re.fullmatch(r"\s*([1-5])\s*(?:sao|điểm|\*)?\s*", user_message.strip())
    if not m:
        return None  # not a rating -> normal pipeline continues

    rating = int(m.group(1))
    review.rating = rating
    review.answered_at = datetime.now()
    patient = conv.patient
    clinic = db.query(Clinic).filter(Clinic.id == conv.clinic_id).first() if conv.clinic_id else None

    if rating >= 4:
        review.status = "answered"
        # Referral voucher: give the patient a shareable code
        if patient and not patient.referral_code:
            patient.referral_code = "CD" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        db.commit()

        parts = [f"Cảm ơn bạn đã chấm {rating} sao! Đội ngũ phòng khám rất vui khi bạn hài lòng. 💚"]
        if clinic and clinic.google_review_url:
            parts.append(f"Nếu tiện, bạn dành 30 giây để lại đánh giá trên Google giúp phòng khám nhé: {clinic.google_review_url}")
        if patient and patient.referral_code:
            parts.append(f"Tặng bạn mã giới thiệu {patient.referral_code} — bạn bè nhập mã này khi đặt lịch sẽ được ưu đãi, và bạn cũng nhận voucher cho lần khám tới!")
        return "\n".join(parts)

    # Low rating: keep it in-house, alert the team immediately
    review.status = "escalated"
    review.feedback = user_message
    conv.status = "handoff_requested"
    db.commit()
    from backend.app.services.ws_manager import ws_manager
    ws_manager.notify(conv.clinic_id, {"type": "review_alert", "conversation_id": conv.id,
                                       "rating": rating, "patient_id": conv.patient_id})
    return ("Cảm ơn bạn đã phản hồi thẳng thắn — phòng khám thành thật xin lỗi vì trải nghiệm chưa tốt. "
            "Quản lý phòng khám sẽ liên hệ trực tiếp với bạn ngay để lắng nghe và khắc phục. "
            "Bạn có thể chia sẻ thêm điều gì khiến bạn chưa hài lòng không ạ?")


def process_chat_message(db: Session, conversation_id: int, user_message: str) -> Tuple[str, bool]:
    """
    Process an incoming message from the patient.
    Returns: Tuple[ai_response_text, is_handoff_triggered]
    """
    # 1. Get conversation
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        return "Hội thoại không tồn tại.", False
        
    # Check if handoff is already active
    if conv.status == "agent_active":
        return "", False  # Do not respond if human agent is active

    # Suspended clinic (vendor disabled the tenant): the AI must not answer
    if conv.clinic_id:
        _clinic = db.query(Clinic).filter(Clinic.id == conv.clinic_id).first()
        if _clinic and _clinic.is_active is False:
            return ("Xin lỗi bạn, kênh tư vấn tự động hiện đang tạm ngưng. "
                    "Bạn vui lòng liên hệ trực tiếp phòng khám để được hỗ trợ nhé."), False

    # 1b. Review rating interception: patient replies 1-5 to a pending review ask
    review_reply = handle_review_reply(db, conv, user_message)
    if review_reply:
        bot_msg = Message(conversation_id=conversation_id, sender="bot", content=review_reply,
                          evaluation_metadata={"review_flow": True})
        db.add(bot_msg)
        db.commit()
        return review_reply, False

    # 2. Safety filter keyword matching
    safety_rule = check_safety_rules(db, user_message, clinic_id=conv.clinic_id)
    if safety_rule:
        # Trigger handoff
        conv.status = "handoff_requested"
        db.commit()
        
        # Save bot response
        bot_msg = Message(
            conversation_id=conversation_id,
            sender="bot",
            content=safety_rule.fallback_message,
            evaluation_metadata={"safety_triggered": True, "category": safety_rule.category}
        )
        db.add(bot_msg)
        db.commit()
        return safety_rule.fallback_message, True

    # 2b. Plan quota check: block AI replies when the clinic exhausted its monthly quota
    if conv.clinic_id:
        clinic = db.query(Clinic).filter(Clinic.id == conv.clinic_id).first()
        if clinic and clinic.ai_quota_monthly is not None:  # None = unlimited; 0 = blocked
            month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            used = db.query(Message).join(Conversation, Message.conversation_id == Conversation.id).filter(
                Conversation.clinic_id == conv.clinic_id,
                Message.sender == "bot",
                Message.created_at >= month_start
            ).count()
            if used >= clinic.ai_quota_monthly:
                quota_msg = ("Trợ lý AI của phòng khám đã đạt giới hạn hội thoại trong tháng. "
                             "Tôi đã chuyển thông tin của bạn cho lễ tân hỗ trợ trực tiếp, "
                             "hoặc bạn vui lòng liên hệ hotline của phòng khám nhé!")
                conv.status = "handoff_requested"
                bot_msg = Message(
                    conversation_id=conversation_id, sender="bot", content=quota_msg,
                    evaluation_metadata={"quota_exceeded": True}
                )
                db.add(bot_msg)
                db.commit()
                return quota_msg, True

    # 2c. Booking flow: the AI can complete a booking end-to-end inside the chat
    from backend.app.services.booking_flow import handle_booking
    booking_response = handle_booking(db, conv, user_message)
    if booking_response:
        bot_msg = Message(
            conversation_id=conversation_id, sender="bot", content=booking_response,
            evaluation_metadata={"booking_flow": True}
        )
        db.add(bot_msg)
        db.commit()
        return booking_response, False

    # 2d. Revenue signal: patient asked about pricing -> feeds the follow-up automation
    lower_msg = user_message.lower()
    if any(kw in lower_msg for kw in ("giá", "bao nhiêu", "phí")):
        from backend.app.services.booking_flow import _resolve_service
        from backend.app.services.events import emit_event
        svc = _resolve_service(db, conv.clinic_id, lower_msg)
        emit_event(db, conv.clinic_id, "price_asked", patient_id=conv.patient_id,
                   payload={"service_id": svc.id if svc else None,
                            "service_name": svc.name if svc else "dịch vụ da liễu"})
        db.commit()

    # 3. Retrieve chat history for context
    history_msgs = db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).order_by(Message.created_at.asc()).all()
    
    history_formatted = []
    for msg in history_msgs[-10:]: # Limit to last 10 messages
        role = "assistant" if msg.sender == "bot" else "user"
        if msg.sender == "agent":
            role = "assistant" # Count agents as assistant in history
        history_formatted.append({"role": role, "content": msg.content})

    # 4. RAG context preparation (strictly scoped to this conversation's clinic)
    clinic = resolve_clinic(db, conv.clinic_id)
    clinic_name = clinic.name if clinic else "phòng khám"
    locale = locale_for_conversation(conv, clinic)
    rag_context = query_faq_rag(db, user_message, clinic_id=conv.clinic_id, locale=locale,
                                branch_id=conv.branch_id)

    # 5. Build System Prompt from THIS clinic's real identity/data (no hardcoded brand)
    system_prompt = f"""Bạn là trợ lý lễ tân ảo AI chuyên nghiệp của '{clinic_name}'.
Quy tắc hoạt động bắt buộc:
1. KHÔNG được chẩn đoán bệnh, KHÔNG kê đơn thuốc, KHÔNG hướng dẫn người bệnh tự xử lý tại nhà khi có dấu hiệu bất thường.
2. LUÔN trả lời ngắn gọn, lịch sự, xưng tên phòng khám và gọi khách hàng là 'bạn'.
3. Chỉ được trả lời dựa trên thông tin phòng khám được cung cấp dưới đây. Tuyệt đối không tự bịa đặt thông tin, dịch vụ hoặc giá cả không có trong dữ liệu.
4. Nếu khách hàng muốn đặt lịch, hãy thu thập thông tin còn thiếu và gửi booking request. KHÔNG được nói đó là lịch hẹn đã xác nhận hoặc tạo Appointment.
5. ALWAYS answer in the patient's locale: {locale} (vi=Vietnamese, en=English, ja=Japanese).

BỐI CẢNH DỮ LIỆU PHÒNG KHÁM (RAG):
{rag_context}
"""

    ai_response = ""
    evaluation_meta = {}

    # 6. Call LLM (or mock if no client configured)
    if openai_client:
        try:
            messages = [{"role": "system", "content": system_prompt}] + history_formatted + [{"role": "user", "content": user_message}]
            
            # Request response from OpenAI
            response = openai_client.chat.completions.create(
                model=settings.LLM_MODEL,  # 'gpt-5.6-terra'
                messages=messages,
                temperature=0.2,
                max_tokens=500
            )
            ai_response = response.choices[0].message.content
            evaluation_meta["model"] = settings.LLM_MODEL
        except Exception as e:
            print(f"OpenAI API call failed: {e}. Falling back to Mock.")
            ai_response = call_openai_gpt_mock(db, clinic, user_message, locale)
            evaluation_meta["fallback_mock"] = True
    else:
        ai_response = call_openai_gpt_mock(db, clinic, user_message, locale)
        evaluation_meta["fallback_mock"] = True

    # 7. Check if AI response itself implies handoff (e.g. LLM decided it can't answer or requested handoff)
    is_handoff = False
    lower_res = ai_response.lower()
    handoff_triggers = ["chuyển tiếp", "nhân viên y tế", "lễ tân sẽ liên hệ", "gặp người thật", "bác sĩ hỗ trợ trực tiếp"]
    if any(trigger in lower_res for trigger in handoff_triggers) and "cần cấp cứu" in lower_res:
        is_handoff = True
        conv.status = "handoff_requested"
        db.commit()

    # 8. Save bot message to DB
    bot_msg = Message(
        conversation_id=conversation_id,
        sender="bot",
        content=ai_response,
        evaluation_metadata=evaluation_meta
    )
    db.add(bot_msg)
    db.commit()

    return ai_response, is_handoff
