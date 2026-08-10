"""
Copilot: staff ask questions in Vietnamese ("hôm nay thế nào?", "doanh thu tháng này?")
and get answers computed from real data via a closed set of query functions -
no free-form SQL, no hallucinated numbers, RBAC enforced (revenue = owner/admin only).
"""
from typing import Any
from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.app.core.database import get_db
from backend.app.api.deps import FeatureRequired, ROLE_OWNER, verify_receptionist_or_above
from backend.app.models.models import (
    Appointment, Conversation, PatientLead, RevenueRecord, PatientPackage, User
)
from backend.app.schemas.schemas import CopilotAsk
from backend.app.services.features import COPILOT

router = APIRouter(dependencies=[Depends(FeatureRequired(COPILOT))])

fmt_money = lambda v: f"{v:,.0f}đ"  # noqa: E731


def _scoped(query, model, user: User):
    if user.clinic_id:
        return query.filter(model.clinic_id == user.clinic_id)
    return query


def _range_today():
    today = date.today()
    return datetime.combine(today, datetime.min.time()), datetime.combine(today, datetime.max.time())


def _range_month():
    start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, datetime.now()


def answer_appointments(db: Session, user: User, month: bool) -> str:
    start, end = _range_month() if month else _range_today()
    query = _scoped(db.query(Appointment), Appointment, user).filter(
        Appointment.start_time >= start, Appointment.start_time <= end
    )
    if user.doctor_id:
        query = query.filter(Appointment.doctor_id == user.doctor_id)
    appts = query.order_by(Appointment.start_time.asc()).all()
    label = "tháng này" if month else "hôm nay"
    scope = " của bác sĩ" if user.doctor_id else ""

    if not appts:
        return f"Không có lịch hẹn nào{scope} {label}."
    by_status = {}
    for a in appts:
        by_status[a.status] = by_status.get(a.status, 0) + 1
    lines = [f"Có {len(appts)} lịch hẹn{scope} {label} "
             f"({by_status.get('pending', 0)} chờ xác nhận, {by_status.get('confirmed', 0)} đã xác nhận, "
             f"{by_status.get('completed', 0)} hoàn thành)."]
    for a in appts[:5]:
        lines.append(f"• {a.start_time.strftime('%H:%M %d/%m')} — {a.patient.full_name if a.patient else '?'} "
                     f"({a.service.name if a.service else '?'}) [{a.status}]")
    if len(appts) > 5:
        lines.append(f"... và {len(appts) - 5} ca khác.")
    return "\n".join(lines)


def answer_revenue(db: Session, user: User, month: bool) -> str:
    if user.role != ROLE_OWNER:
        return "Xin lỗi, số liệu doanh thu chỉ dành cho chủ phòng khám."
    start, end = _range_month() if month else _range_today()
    records = _scoped(db.query(RevenueRecord), RevenueRecord, user).filter(
        RevenueRecord.recorded_at >= start, RevenueRecord.recorded_at <= end
    ).all()
    label = "tháng này" if month else "hôm nay"
    total = sum(r.amount for r in records)
    ai_total = sum(r.amount for r in records if (r.source or "").startswith("ai_"))
    pkg_total = sum(r.amount for r in records if r.source == "package")
    return (f"Doanh thu {label}: {fmt_money(total)} ({len(records)} giao dịch).\n"
            f"• AI tạo ra: {fmt_money(ai_total)}\n"
            f"• Bán gói liệu trình: {fmt_money(pkg_total)}\n"
            f"• Còn lại (lễ tân/khác): {fmt_money(total - ai_total - pkg_total)}")


def answer_patients(db: Session, user: User) -> str:
    start, end = _range_today()
    new_today = _scoped(db.query(PatientLead), PatientLead, user).filter(
        PatientLead.created_at >= start
    ).count()
    total = _scoped(db.query(PatientLead), PatientLead, user).count()
    convs_today = _scoped(db.query(Conversation), Conversation, user).filter(
        Conversation.created_at >= start
    ).count()
    return (f"Hôm nay có {new_today} khách hàng mới và {convs_today} hội thoại mới. "
            f"Tổng cộng phòng khám đang có {total} hồ sơ khách hàng.")


def answer_packages(db: Session, user: User) -> str:
    packs = _scoped(db.query(PatientPackage), PatientPackage, user).filter(
        PatientPackage.status == "active"
    ).all()
    if not packs:
        return "Hiện chưa có khách nào đang sở hữu gói liệu trình còn hiệu lực."
    remaining_value = sum(
        (p.sessions_total - p.sessions_used) / p.sessions_total * (p.amount_paid or 0)
        for p in packs if p.sessions_total
    )
    return (f"Đang có {len(packs)} gói liệu trình còn hiệu lực. "
            f"Giá trị buổi chưa sử dụng (nghĩa vụ dịch vụ): {fmt_money(remaining_value)}. "
            f"Automation sẽ tự nhắc khách dùng buổi trước khi hết hạn.")


def answer_noshow(db: Session, user: User) -> str:
    start, _ = _range_month()
    appts = _scoped(db.query(Appointment), Appointment, user).filter(
        Appointment.start_time >= start,
        Appointment.status.in_(["completed", "no_show"])
    ).all()
    if not appts:
        return "Tháng này chưa có ca nào kết thúc để tính tỷ lệ vắng mặt."
    no_show = sum(1 for a in appts if a.status == "no_show")
    rate = no_show / len(appts) * 100
    return (f"Tỷ lệ no-show tháng này: {rate:.1f}% ({no_show}/{len(appts)} ca đã kết thúc). "
            f"Nhắc lịch tự động + đặt cọc đang giúp giữ tỷ lệ này thấp.")


HELP_TEXT = ("Tôi có thể trả lời:\n"
             "• 'Hôm nay có bao nhiêu lịch hẹn?'\n"
             "• 'Doanh thu hôm nay / tháng này?' (chủ phòng khám)\n"
             "• 'Có bao nhiêu khách mới?'\n"
             "• 'Tình hình gói liệu trình?'\n"
             "• 'Tỷ lệ no-show?'")


@router.post("/ask")
def copilot_ask(
    ask: CopilotAsk,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    q = ask.question.lower()
    month = "tháng" in q

    if any(k in q for k in ("doanh thu", "tiền", "revenue", "roi", "kiếm được")):
        answer = answer_revenue(db, current_user, month)
    elif any(k in q for k in ("no-show", "no show", "vắng", "bỏ lịch")):
        answer = answer_noshow(db, current_user)
    elif any(k in q for k in ("gói", "liệu trình", "package")):
        answer = answer_packages(db, current_user)
    elif any(k in q for k in ("khách mới", "bệnh nhân mới", "bao nhiêu khách", "hội thoại")):
        answer = answer_patients(db, current_user)
    elif any(k in q for k in ("lịch hẹn", "lịch", "hẹn", "hôm nay", "appointment")):
        answer = answer_appointments(db, current_user, month)
    else:
        answer = HELP_TEXT

    return {"question": ask.question, "answer": answer, "answered_at": datetime.now().isoformat()}
