"""
Automation control panel: clinic staff see & tune the revenue automations
(follow-up, recall, win-back, review ask, waitlist fill) plus their activity log,
review results and the waitlist.
"""
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend.app.core.database import get_db
from backend.app.api.deps import verify_receptionist_or_above, verify_owner_or_admin
from backend.app.models.models import (
    AutomationRule, ScheduledAction, ReviewRequest, WaitlistEntry, PatientLead, User
)
from backend.app.schemas.schemas import AutomationRuleUpdate, WaitlistCreate
from backend.app.services.audit import log_action

router = APIRouter()

TRIGGER_LABELS = {
    "price_asked": "Khách hỏi giá",
    "appointment_created": "Đặt lịch mới",
    "appointment_completed": "Hoàn thành buổi khám",
    "appointment_cancelled": "Khách hủy lịch",
    "package_used_up": "Dùng hết gói liệu trình",
}


@router.get("/rules")
def list_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    rules = db.query(AutomationRule).filter(
        AutomationRule.clinic_id == (current_user.clinic_id or 0)
    ).order_by(AutomationRule.id.asc()).all()
    result = []
    for r in rules:
        sent_count = db.query(ScheduledAction).filter(
            ScheduledAction.rule_id == r.id, ScheduledAction.status == "sent"
        ).count()
        result.append({
            "id": r.id, "name": r.name, "enabled": r.enabled,
            "trigger_type": r.trigger_type,
            "trigger_label": TRIGGER_LABELS.get(r.trigger_event, "Định kỳ" if r.trigger_type == "recurring" else r.trigger_event),
            "delay_minutes": r.delay_minutes,
            "message_template": r.message_template,
            "action_type": r.action_type,
            "is_system": r.is_system,
            "sent_count": sent_count,
        })
    return result


@router.put("/rules/{rule_id}")
def update_rule(
    rule_id: int,
    rule_in: AutomationRuleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
) -> Any:
    rule = db.query(AutomationRule).filter(AutomationRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Không tìm thấy automation")
    if current_user.clinic_id and rule.clinic_id != current_user.clinic_id:
        raise HTTPException(status_code=403, detail="Không thuộc phòng khám của bạn.")

    data = rule_in.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(rule, key, value)
    log_action(db, current_user.id, "update_automation", f"Cập nhật automation '{rule.name}' (enabled={rule.enabled})")
    db.commit()
    return {"id": rule.id, "enabled": rule.enabled, "message_template": rule.message_template,
            "delay_minutes": rule.delay_minutes}


@router.get("/actions")
def recent_actions(
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    query = db.query(ScheduledAction, AutomationRule, PatientLead).outerjoin(
        AutomationRule, ScheduledAction.rule_id == AutomationRule.id
    ).outerjoin(PatientLead, ScheduledAction.patient_id == PatientLead.id)
    if current_user.clinic_id:
        query = query.filter(ScheduledAction.clinic_id == current_user.clinic_id)
    rows = query.order_by(ScheduledAction.id.desc()).limit(min(limit, 200)).all()
    return [{
        "id": a.id,
        "rule_name": r.name if r else "?",
        "patient_name": p.full_name if p else "?",
        "status": a.status,
        "due_at": a.due_at,
        "executed_at": a.executed_at,
    } for a, r, p in rows]


@router.get("/reviews")
def list_reviews(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    query = db.query(ReviewRequest, PatientLead).join(
        PatientLead, ReviewRequest.patient_id == PatientLead.id
    )
    if current_user.clinic_id:
        query = query.filter(ReviewRequest.clinic_id == current_user.clinic_id)
    rows = query.order_by(ReviewRequest.id.desc()).limit(100).all()
    return [{
        "id": rv.id, "patient_name": p.full_name, "patient_phone": p.phone,
        "rating": rv.rating, "status": rv.status, "feedback": rv.feedback,
        "sent_at": rv.sent_at, "answered_at": rv.answered_at,
    } for rv, p in rows]


@router.get("/waitlist")
def list_waitlist(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    query = db.query(WaitlistEntry)
    if current_user.clinic_id:
        query = query.filter(WaitlistEntry.clinic_id == current_user.clinic_id)
    rows = query.filter(WaitlistEntry.status.in_(["waiting", "notified"]))\
        .order_by(WaitlistEntry.created_at.asc()).all()
    return [{
        "id": w.id,
        "patient_name": w.patient.full_name if w.patient else "?",
        "patient_phone": w.patient.phone if w.patient else "",
        "service_name": w.service.name if w.service else "Bất kỳ",
        "preferred_date": w.preferred_date,
        "status": w.status,
        "created_at": w.created_at,
    } for w in rows]


@router.post("/waitlist")
def add_waitlist(
    entry_in: WaitlistCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    patient = db.query(PatientLead).filter(PatientLead.id == entry_in.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách hàng")
    entry = WaitlistEntry(
        clinic_id=current_user.clinic_id or patient.clinic_id,
        patient_id=entry_in.patient_id,
        service_id=entry_in.service_id,
        preferred_date=entry_in.preferred_date
    )
    db.add(entry)
    log_action(db, current_user.id, "add_waitlist", f"Thêm {patient.full_name} vào danh sách chờ")
    db.commit()
    return {"id": entry.id, "status": entry.status}


@router.delete("/waitlist/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_waitlist(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
):
    entry = db.query(WaitlistEntry).filter(WaitlistEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Không tìm thấy")
    if current_user.clinic_id and entry.clinic_id != current_user.clinic_id:
        raise HTTPException(status_code=403, detail="Không thuộc phòng khám của bạn.")
    entry.status = "cancelled"
    db.commit()
    return
