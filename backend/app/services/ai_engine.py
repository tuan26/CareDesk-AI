import json
import re
from datetime import datetime, date, time, timedelta
from typing import Dict, Any, List, Tuple, Optional
from sqlalchemy.orm import Session
from backend.app.core.config import settings
from backend.app.models.models import (
    Conversation, Message, PatientLead, Service, Doctor, WorkingSchedule, Appointment, AISafetyRule
)

# Initialize OpenAI client if API key is provided
openai_client = None
if settings.OPENAI_API_KEY:
    try:
        from openai import OpenAI
        openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
    except Exception as e:
        print(f"Failed to initialize OpenAI client: {e}")


def check_safety_rules(db: Session, text: str) -> Optional[AISafetyRule]:
    """
    Check if the text contains any dangerous keywords defined in AISafetyRule.
    Returns the matched AISafetyRule or None.
    """
    rules = db.query(AISafetyRule).all()
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


def query_faq_rag(db: Session, query: str) -> str:
    """
    Simple RAG implementation: Matches query keywords with Service description and service FAQ database.
    """
    services = db.query(Service).all()
    context_chunks = []
    
    # Match services based on basic keyword matching
    query_lower = query.lower()
    for service in services:
        matched = False
        if service.name.lower() in query_lower:
            matched = True
        else:
            for word in service.name.lower().split():
                if len(word) > 2 and word in query_lower:
                    matched = True
                    break
                    
        if matched:
            chunk = f"Dịch vụ: {service.name}. Giá: {service.price:,.0f} VNĐ. Thời lượng: {service.duration_minutes} phút. Mô tả: {service.description}."
            if service.preparation_instructions:
                chunk += f" Chuẩn bị trước khi khám: {service.preparation_instructions}"
            context_chunks.append(chunk)
            
            # Append FAQs of this service
            if service.faq_data:
                for faq in service.faq_data:
                    context_chunks.append(f"Hỏi: {faq['question']} -> Đáp: {faq['answer']}")
                    
    # If no services matched, dump all services info briefly
    if not context_chunks:
        clinic_info = "Phòng khám Da liễu Thẩm mỹ CareDesk. Địa chỉ: 123 Đường Ba Tháng Hai, Q.10, TP.HCM. Hotline: 0901234567. Mở cửa: 08:00 - 20:00."
        context_chunks.append(clinic_info)
        for service in services:
            context_chunks.append(f"- Dịch vụ {service.name}: giá {service.price:,.0f} VNĐ (Thời gian: {service.duration_minutes} phút).")
            
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


def call_openai_gpt_mock(system_prompt: str, user_query: str, history: List[Dict[str, str]]) -> str:
    """
    Mock AI response when OpenAI API Key is missing or fails.
    """
    query_lower = user_query.lower()
    
    # 1. FAQ response mock
    if "giá" in query_lower or "bao nhiêu" in query_lower or "phí" in query_lower:
        if "mụn" in query_lower:
            return "Chào bạn, liệu trình Điều trị mụn Chuẩn Y Khoa tại CareDesk có giá là 450,000đ cho 75 phút điều trị toàn bộ 12 bước chuyên sâu. Bạn có muốn đặt lịch hẹn thực hiện dịch vụ này không?"
        elif "khám" in query_lower or "soi da" in query_lower:
            return "Chào bạn, phí khám da liễu trực tiếp với Bác sĩ chuyên khoa tại CareDesk là 150,000đ (đã bao gồm soi da kỹ thuật số). Bạn có muốn đặt lịch hẹn khám không?"
        elif "laser" in query_lower or "sẹo" in query_lower:
            return "Chào bạn, dịch vụ Laser Fractional CO2 trị sẹo rỗ có giá là 1,200,000đ cho mỗi buổi điều trị. Bạn có muốn đặt lịch tư vấn không?"
        else:
            return "Chào bạn, CareDesk hiện cung cấp các dịch vụ: 1. Khám da liễu với Bác sĩ (150k), 2. Trị mụn Chuẩn Y khoa (450k), 3. Laser Fractional CO2 trị sẹo rỗ (1.200k). Bạn đang quan tâm dịch vụ nào ạ?"
            
    if "địa chỉ" in query_lower or "ở đâu" in query_lower or "chi nhánh" in query_lower:
        return "CareDesk có 2 chi nhánh chính làm việc từ 08:00 đến 20:00:\n1. Chi nhánh Quận 10 (Trụ sở): 123 Đường Ba Tháng Hai, Q.10, TP.HCM.\n2. Chi nhánh Quận 1: 456 Đường Nguyễn Huệ, Q.1, TP.HCM.\nBạn ở gần khu vực nào hơn ạ?"

    if "giờ làm việc" in query_lower or "mở cửa" in query_lower or "mấy giờ" in query_lower or ("làm việc" in query_lower and "giờ" in query_lower):
        return "Phòng khám CareDesk mở cửa tất cả các ngày trong tuần. Chi nhánh Quận 10 hoạt động từ 08:00 đến 20:00, Chi nhánh Quận 1 hoạt động từ 09:00 đến 21:00. Bạn dự định ghé chi nhánh nào ạ?"


    # 2. Booking response mock
    if "đặt lịch" in query_lower or "hẹn" in query_lower or "book" in query_lower or "khám" in query_lower:
        entities = extract_booking_entities_mock(user_query)
        missing = []
        if not entities["full_name"]:
            missing.append("Họ và Tên")
        if not entities["phone"]:
            missing.append("Số điện thoại liên hệ")
        if not entities["service_name"]:
            missing.append("Dịch vụ muốn thực hiện (Khám da/Trị mụn/Laser)")
            
        if missing:
            return f"Chào bạn! Tôi rất sẵn lòng hỗ trợ bạn đặt lịch hẹn. Để đăng ký, vui lòng cung cấp giúp tôi thông tin còn thiếu: {', '.join(missing)} nhé ạ."
            
        # If we have some info, simulate proposal of slot
        target_date = entities["date_str"] or (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        return f"Dạ, tôi ghi nhận thông tin đăng ký khám của bạn:\n- Họ tên: {entities['full_name']}\n- Số điện thoại: {entities['phone']}\n- Dịch vụ: {entities['service_name']}\nTôi xin đề xuất 3 khung giờ trống vào ngày {target_date} tại Chi nhánh Quận 10:\n1. 09:00 sáng\n2. 10:30 sáng\n3. 15:00 chiều\nBạn vui lòng chọn một khung giờ phù hợp hoặc đề xuất giờ khác nhé."

    return "Chào bạn, tôi là trợ lý ảo CareDesk AI. Tôi có thể giúp bạn giải đáp bảng giá dịch vụ, tìm hiểu địa chỉ phòng khám hoặc hỗ trợ đặt lịch hẹn khám nhanh chóng. Bạn cần tôi hỗ trợ thông tin gì hôm nay ạ?"


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

    # 2. Safety filter keyword matching
    safety_rule = check_safety_rules(db, user_message)
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

    # 4. RAG context preparation
    rag_context = query_faq_rag(db, user_message)
    
    # 5. Build System Prompt
    system_prompt = f"""Bạn là trợ lý lễ tân ảo AI chuyên nghiệp của 'Phòng khám Da liễu Thẩm mỹ CareDesk'.
Quy tắc hoạt động bắt buộc:
1. KHÔNG được chẩn đoán bệnh, KHÔNG kê đơn thuốc, KHÔNG hướng dẫn người bệnh tự xử lý tại nhà khi có dấu hiệu bất thường.
2. LUÔN trả lời ngắn gọn, lịch sự, xưng 'CareDesk' và gọi khách hàng là 'bạn'.
3. Chỉ được trả lời dựa trên thông tin phòng khám được cung cấp dưới đây. Tuyệt đối không tự bịa đặt thông tin hoặc giá cả dịch vụ.
4. Nếu khách hàng muốn đặt lịch, hãy khéo léo hỏi các thông tin còn thiếu bao gồm: Họ tên, Số điện thoại, Dịch vụ muốn thực hiện (Khám da liễu, Trị mụn Chuẩn Y khoa, Laser trị sẹo rỗ). Sau khi có đủ thông tin, đề xuất giờ trống và hướng dẫn xác nhận.

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
            ai_response = call_openai_gpt_mock(system_prompt, user_message, history_formatted)
            evaluation_meta["fallback_mock"] = True
    else:
        ai_response = call_openai_gpt_mock(system_prompt, user_message, history_formatted)
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
