"""
Event bus + Automation Engine.

Every business fact is appended to `domain_events`. The engine (running in the
background scheduler) matches events against per-clinic `automation_rules`,
schedules delayed actions (`scheduled_actions`), cancels them when a
cancel-event arrives (e.g. patient booked -> stop follow-ups), and dispatches
due actions through the patient's channel (web widget / Zalo / Facebook / SMS).

Revenue features (follow-up, recall, win-back, review ask, waitlist fill,
package expiry) are all just rules — configuration, not code.
"""
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from backend.app.models.models import (
    DomainEvent, AutomationRule, ScheduledAction, PatientLead, Conversation,
    Message, Appointment, Service, ReviewRequest, WaitlistEntry, PatientPackage, Clinic
)


def emit_event(db: Session, clinic_id: Optional[int], event_type: str,
               patient_id: Optional[int] = None, payload: dict = None):
    """Append a domain event. Committed together with the caller's transaction."""
    db.add(DomainEvent(
        clinic_id=clinic_id, event_type=event_type,
        patient_id=patient_id, payload=payload or {}
    ))


def render_template(db: Session, template: str, patient: Optional[PatientLead],
                    payload: dict, clinic_id: Optional[int]) -> str:
    clinic = db.query(Clinic).filter(Clinic.id == clinic_id).first() if clinic_id else None
    service_name = payload.get("service_name", "")
    if not service_name and payload.get("service_id"):
        svc = db.query(Service).filter(Service.id == payload["service_id"]).first()
        service_name = svc.name if svc else ""
    values = {
        "name": patient.full_name if patient else "bạn",
        "service": service_name or "dịch vụ",
        "clinic": clinic.name if clinic else "phòng khám",
        "phone": (clinic.phone if clinic else "") or "",
        "slot": payload.get("slot", ""),
        "date": payload.get("date", ""),
    }
    text = template or ""
    for key, val in values.items():
        text = text.replace("{" + key + "}", str(val))
    return text


def deliver_to_patient(db: Session, patient: PatientLead, text: str) -> bool:
    """
    Push a proactive message to a patient through their best channel:
    last conversation channel (Zalo/FB push, web = stored for widget polling),
    falling back to ZNS/SMS by phone.

    The return value decides whether the ScheduledAction is marked "sent" or
    "failed", so it must reflect a real delivery. A web conversation counts as
    delivered the moment the Message row exists — the widget polls for it — but
    a Zalo/FB push or an SMS only counts if the provider accepted it.
    """
    from backend.app.services.channel_gateway import (
        send_zalo_message, send_facebook_message, send_zns_or_sms
    )
    conv = db.query(Conversation).filter(
        Conversation.patient_id == patient.id
    ).order_by(Conversation.updated_at.desc()).first()

    if conv:
        db.add(Message(conversation_id=conv.id, sender="bot", content=text,
                       evaluation_metadata={"automation": True}))
        conv.updated_at = datetime.utcnow()
        if conv.channel == "zalo" and patient.external_id:
            return send_zalo_message(db, conv.clinic_id, patient.external_id, text)
        if conv.channel == "facebook" and patient.external_id:
            return send_facebook_message(db, conv.clinic_id, patient.external_id, text)
        if conv.channel == "web":
            return True  # stored; the widget will pick it up on its next poll
        if patient.phone:
            return send_zns_or_sms(db, conv.clinic_id, patient.phone, text).delivered
        return False

    if patient.phone:
        return send_zns_or_sms(db, patient.clinic_id, patient.phone, text).delivered
    return False


# ---------- Engine: process events into scheduled actions ----------

def process_new_events(db: Session):
    events = db.query(DomainEvent).filter(DomainEvent.processed == False)\
        .order_by(DomainEvent.id.asc()).limit(200).all()  # noqa: E712

    for event in events:
        # 1. Cancel pending actions whose rule says this event cancels them
        if event.patient_id:
            pendings = db.query(ScheduledAction, AutomationRule).join(
                AutomationRule, ScheduledAction.rule_id == AutomationRule.id
            ).filter(
                ScheduledAction.patient_id == event.patient_id,
                ScheduledAction.status == "pending"
            ).all()
            for action, rule in pendings:
                if rule.cancel_on_events and event.event_type in rule.cancel_on_events:
                    action.status = "cancelled"

        # 2. Match event-triggered rules -> schedule actions
        rules = db.query(AutomationRule).filter(
            AutomationRule.clinic_id == (event.clinic_id or 0),
            AutomationRule.trigger_type == "event",
            AutomationRule.trigger_event == event.event_type,
            AutomationRule.enabled == True  # noqa: E712
        ).all()
        for rule in rules:
            cond = rule.condition or {}
            if cond.get("service_id") and (event.payload or {}).get("service_id") != cond["service_id"]:
                continue
            db.add(ScheduledAction(
                clinic_id=event.clinic_id,
                rule_id=rule.id,
                patient_id=event.patient_id,
                due_at=datetime.now() + timedelta(minutes=rule.delay_minutes or 0),
                payload=event.payload or {}
            ))

        event.processed = True
    db.commit()
    return len(events)


def run_recurring_rules(db: Session):
    """Daily-style rules: win-back inactive patients, package expiry reminders."""
    rules = db.query(AutomationRule).filter(
        AutomationRule.trigger_type == "recurring",
        AutomationRule.enabled == True  # noqa: E712
    ).all()
    now = datetime.now()

    for rule in rules:
        cond = rule.condition or {}

        # Win-back: patients whose last appointment ended > inactive_days ago
        if cond.get("inactive_days"):
            cutoff = now - timedelta(days=cond["inactive_days"])
            patients = db.query(PatientLead).filter(PatientLead.clinic_id == rule.clinic_id).all()
            for p in patients:
                last = db.query(Appointment).filter(
                    Appointment.patient_id == p.id,
                    Appointment.status == "completed"
                ).order_by(Appointment.start_time.desc()).first()
                if not last or last.start_time.replace(tzinfo=None) > cutoff:
                    continue
                recent = db.query(ScheduledAction).filter(
                    ScheduledAction.rule_id == rule.id,
                    ScheduledAction.patient_id == p.id,
                    ScheduledAction.created_at >= now - timedelta(days=90)
                ).first()
                if recent:
                    continue  # don't nag more than once per quarter
                db.add(ScheduledAction(
                    clinic_id=rule.clinic_id, rule_id=rule.id, patient_id=p.id,
                    due_at=now, payload={}
                ))

        # Package expiring soon with unused sessions
        if cond.get("package_expiring_days"):
            edge = now + timedelta(days=cond["package_expiring_days"])
            packs = db.query(PatientPackage).filter(
                PatientPackage.clinic_id == rule.clinic_id,
                PatientPackage.status == "active",
                PatientPackage.expires_at != None,  # noqa: E711
                PatientPackage.expires_at <= edge,
                PatientPackage.sessions_used < PatientPackage.sessions_total
            ).all()
            for pp in packs:
                recent = db.query(ScheduledAction).filter(
                    ScheduledAction.rule_id == rule.id,
                    ScheduledAction.patient_id == pp.patient_id,
                    ScheduledAction.created_at >= now - timedelta(days=14)
                ).first()
                if recent:
                    continue
                remaining = pp.sessions_total - pp.sessions_used
                db.add(ScheduledAction(
                    clinic_id=rule.clinic_id, rule_id=rule.id, patient_id=pp.patient_id,
                    due_at=now,
                    payload={"service_name": pp.package.name if pp.package else "gói liệu trình",
                             "remaining": remaining,
                             "expires": pp.expires_at.strftime("%d/%m/%Y") if pp.expires_at else ""}
                ))
    db.commit()


def dispatch_due_actions(db: Session):
    due = db.query(ScheduledAction).filter(
        ScheduledAction.status == "pending",
        ScheduledAction.due_at <= datetime.now()
    ).limit(100).all()

    sent = 0
    for action in due:
        rule = db.query(AutomationRule).filter(AutomationRule.id == action.rule_id).first()
        patient = db.query(PatientLead).filter(PatientLead.id == action.patient_id).first()
        if not rule or not patient:
            action.status = "cancelled"
            continue
        try:
            if rule.action_type == "send_message":
                text = render_template(db, rule.message_template, patient, action.payload or {}, action.clinic_id)
                extra = ""
                if (action.payload or {}).get("remaining"):
                    extra = f" (Còn {action.payload['remaining']} buổi, hạn {action.payload.get('expires', '')})"
                delivered = deliver_to_patient(db, patient, text + extra)
                action.status = "sent" if delivered else "failed"

            elif rule.action_type == "review_request":
                text = render_template(db, rule.message_template, patient, action.payload or {}, action.clinic_id)
                db.add(ReviewRequest(
                    clinic_id=action.clinic_id, patient_id=patient.id,
                    appointment_id=(action.payload or {}).get("appointment_id")
                ))
                delivered = deliver_to_patient(db, patient, text)
                action.status = "sent" if delivered else "failed"

            elif rule.action_type == "notify_waitlist":
                action.status = "sent" if _notify_waitlist(db, action) else "cancelled"

            else:
                action.status = "failed"
        except Exception as e:
            print(f"[AUTOMATION ERROR] action #{action.id}: {e}")
            action.status = "failed"

        action.executed_at = datetime.now()
        sent += 1
    db.commit()
    return sent


def _notify_waitlist(db: Session, action: ScheduledAction) -> bool:
    """A slot was freed (cancellation): ping up to 3 matching waitlisted patients."""
    payload = action.payload or {}
    query = db.query(WaitlistEntry).filter(
        WaitlistEntry.clinic_id == action.clinic_id,
        WaitlistEntry.status == "waiting"
    )
    if payload.get("service_id"):
        query = query.filter(
            (WaitlistEntry.service_id == payload["service_id"]) | (WaitlistEntry.service_id == None)  # noqa: E711
        )
    entries = query.order_by(WaitlistEntry.created_at.asc()).limit(3).all()
    if not entries:
        return False

    slot_info = f"{payload.get('slot', '')} ngày {payload.get('date', '')}".strip()
    service_name = payload.get("service_name", "dịch vụ")
    for entry in entries:
        text = (f"Tin vui từ phòng khám! Vừa có khách hủy lịch nên trống ca {slot_info} "
                f"({service_name}). Bạn muốn nhận ca này không? "
                f"Nhắn 'đặt lịch {service_name} ngày {payload.get('date', '')} lúc {payload.get('slot', '')}' để em giữ chỗ ngay nhé — ai xác nhận trước được trước ạ!")
        deliver_to_patient(db, entry.patient, text)
        entry.status = "notified"
        entry.notified_at = datetime.now()
    return True


def run_engine_tick(db: Session):
    process_new_events(db)
    dispatch_due_actions(db)


# ---------- Default per-clinic rules (seeded on clinic creation) ----------

DEFAULT_RULES = [
    dict(name="Follow-up khách hỏi giá (2 ngày)", trigger_type="event", trigger_event="price_asked",
         delay_minutes=2 * 24 * 60, cancel_on_events=["booking_request_created", "appointment_created"], action_type="send_message",
         message_template="Chào {name}, hôm trước bạn có quan tâm {service} bên {clinic}. Bạn còn muốn tìm hiểu thêm không ạ? Em có thể tư vấn chi tiết hoặc giữ lịch khám cho bạn nhé!"),
    # Off until the clinic trusts the system: a second unsolicited nudge about a
    # promotion is the one most likely to be reported as spam, and a Zalo OA
    # that collects spam reports early is hard to recover.
    dict(name="Follow-up khách hỏi giá (5 ngày - ưu đãi)", trigger_type="event", trigger_event="price_asked",
         delay_minutes=5 * 24 * 60, cancel_on_events=["booking_request_created", "appointment_created"], action_type="send_message",
         enabled=False,
         message_template="Chào {name}, {clinic} đang có ưu đãi cho {service} trong tuần này. Bạn muốn em giữ một suất khám tư vấn miễn phí không ạ?"),
    dict(name="Nhắc tái khám sau 30 ngày", trigger_type="event", trigger_event="appointment_completed",
         delay_minutes=30 * 24 * 60, cancel_on_events=["appointment_created"], action_type="send_message",
         message_template="Chào {name}, đã 1 tháng kể từ buổi {service} tại {clinic}. Bác sĩ khuyên nên tái khám để theo dõi tiến triển da. Bạn muốn em đặt lịch tuần này không ạ?"),
    dict(name="Xin đánh giá sau khám (2 giờ)", trigger_type="event", trigger_event="appointment_completed",
         delay_minutes=120, action_type="review_request",
         message_template="Chào {name}, cảm ơn bạn đã sử dụng {service} tại {clinic} hôm nay! Bạn chấm chất lượng dịch vụ mấy điểm (1-5) ạ? Trả lời bằng một con số giúp em nhé."),
    # Off by default: this fires at the entire back catalogue at once. Sending
    # it on day one, before the clinic has watched the system behave, is the
    # fastest way to a spam complaint against a brand-new Zalo OA.
    dict(name="Đánh thức khách cũ (6 tháng)", trigger_type="recurring", condition={"inactive_days": 180},
         action_type="send_message", enabled=False,
         message_template="Chào {name}, lâu rồi chưa gặp bạn tại {clinic}! Bên em đang có chương trình soi da miễn phí cho khách hàng thân thiết. Bạn ghé chơi tuần này nhé?"),
    dict(name="Nhắc gói liệu trình sắp hết hạn", trigger_type="recurring", condition={"package_expiring_days": 14},
         action_type="send_message",
         message_template="Chào {name}, gói {service} của bạn tại {clinic} vẫn còn buổi chưa sử dụng."),
    dict(name="Lấp chỗ trống từ danh sách chờ", trigger_type="event", trigger_event="appointment_cancelled",
         delay_minutes=0, action_type="notify_waitlist", message_template=""),
    dict(name="Mời quay lại khi dùng hết gói", trigger_type="event", trigger_event="package_used_up",
         delay_minutes=60, action_type="send_message",
         message_template="Chào {name}, bạn vừa hoàn thành trọn vẹn gói {service} tại {clinic} — chúc mừng làn da mới! Khách hoàn thành gói được giảm 15% khi gia hạn gói tiếp theo. Bạn muốn em tư vấn không ạ?"),
]


def seed_default_automations(db: Session, clinic_id: int):
    existing = db.query(AutomationRule).filter(AutomationRule.clinic_id == clinic_id).count()
    if existing:
        return
    for spec in DEFAULT_RULES:
        # Most rules ship on; the two most spam-prone ship off and the clinic
        # turns them on from the Automation screen once they trust the system.
        spec = {"enabled": True, **spec}
        db.add(AutomationRule(clinic_id=clinic_id, is_system=True, **spec))
    db.commit()
