"""
Business reports for clinic owners: expected revenue, no-show rate,
chat -> booking conversion, peak hours. This is the screen that shows
the clinic its ROI from the AI receptionist.
"""
from typing import Any, Optional
from datetime import date, datetime, timedelta
from collections import defaultdict
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.app.core.database import get_db
from backend.app.api.deps import verify_owner_or_admin
from backend.app.models.models import (
    Appointment, Conversation, User, RevenueRecord, PatientPackage, Clinic
)

router = APIRouter()


@router.get("/summary")
def get_report_summary(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
) -> Any:
    end_date = end_date or date.today()
    start_date = start_date or (end_date - timedelta(days=29))
    range_start = datetime.combine(start_date, datetime.min.time())
    range_end = datetime.combine(end_date, datetime.max.time())

    appt_query = db.query(Appointment).filter(
        Appointment.start_time >= range_start,
        Appointment.start_time <= range_end
    )
    conv_query = db.query(Conversation).filter(
        Conversation.created_at >= range_start,
        Conversation.created_at <= range_end
    )
    if current_user.clinic_id:
        appt_query = appt_query.filter(Appointment.clinic_id == current_user.clinic_id)
        conv_query = conv_query.filter(Conversation.clinic_id == current_user.clinic_id)

    appointments = appt_query.all()
    conversations = conv_query.all()

    # Status breakdown
    status_counts = defaultdict(int)
    for a in appointments:
        status_counts[a.status] += 1

    completed = status_counts.get("completed", 0)
    no_show = status_counts.get("no_show", 0)
    finished = completed + no_show
    no_show_rate = round(no_show / finished * 100, 1) if finished else 0.0

    # Revenue (expected = confirmed + completed; actual = completed only)
    revenue_by_service = defaultdict(lambda: {"count": 0, "revenue": 0.0})
    revenue_by_doctor = defaultdict(lambda: {"count": 0, "revenue": 0.0})
    expected_revenue = 0.0
    actual_revenue = 0.0
    for a in appointments:
        price = a.service.price if a.service else 0.0
        if a.status in ("confirmed", "completed"):
            expected_revenue += price
            svc = revenue_by_service[a.service.name if a.service else "Khác"]
            svc["count"] += 1
            svc["revenue"] += price
            doc = revenue_by_doctor[a.doctor.name if a.doctor else "Khác"]
            doc["count"] += 1
            doc["revenue"] += price
        if a.status == "completed":
            actual_revenue += price

    # Peak hours (8h - 20h)
    peak_hours = {h: 0 for h in range(8, 21)}
    for a in appointments:
        hour = a.start_time.hour
        if 8 <= hour <= 20:
            peak_hours[hour] += 1

    # Chat -> booking conversion & handoff rate.
    # Conversion counts bookings CREATED in the range (a booking made today for next week counts today).
    created_query = db.query(Appointment).filter(
        Appointment.created_at >= range_start,
        Appointment.created_at <= range_end
    )
    if current_user.clinic_id:
        created_query = created_query.filter(Appointment.clinic_id == current_user.clinic_id)
    created_appointments = created_query.all()

    total_convs = len(conversations)
    handoff_convs = sum(1 for c in conversations if c.status in ("handoff_requested", "agent_active"))
    ai_booked = sum(1 for a in created_appointments if a.note and "trợ lý AI" in a.note)
    conversion_rate = round(len(created_appointments) / total_convs * 100, 1) if total_convs else 0.0
    handoff_rate = round(handoff_convs / total_convs * 100, 1) if total_convs else 0.0

    # ---- Revenue ledger (source of truth for "AI made you X") ----
    ledger_query = db.query(RevenueRecord).filter(
        RevenueRecord.recorded_at >= range_start,
        RevenueRecord.recorded_at <= range_end
    )
    if current_user.clinic_id:
        ledger_query = ledger_query.filter(RevenueRecord.clinic_id == current_user.clinic_id)
    ledger = ledger_query.all()

    ledger_total = sum(r.amount for r in ledger)
    ai_revenue = sum(r.amount for r in ledger if (r.source or "").startswith("ai_"))
    revenue_by_source = defaultdict(float)
    for r in ledger:
        revenue_by_source[r.source or "staff"] += r.amount

    # ROI vs the clinic's subscription fee
    clinic = db.query(Clinic).filter(Clinic.id == current_user.clinic_id).first() if current_user.clinic_id else None
    monthly_fee = (clinic.monthly_fee or 0) if clinic else 0
    roi = round(ai_revenue / monthly_fee, 1) if monthly_fee > 0 else None

    # Returning patients: completed 2+ visits (loyalty signal)
    completed_by_patient = defaultdict(int)
    all_completed_q = db.query(Appointment).filter(Appointment.status == "completed")
    if current_user.clinic_id:
        all_completed_q = all_completed_q.filter(Appointment.clinic_id == current_user.clinic_id)
    for a in all_completed_q.all():
        completed_by_patient[a.patient_id] += 1
    returning_patients = sum(1 for c in completed_by_patient.values() if c >= 2)

    # Prepaid packages: outstanding service obligation (unused session value)
    pkg_query = db.query(PatientPackage).filter(PatientPackage.status == "active")
    if current_user.clinic_id:
        pkg_query = pkg_query.filter(PatientPackage.clinic_id == current_user.clinic_id)
    active_packages = pkg_query.all()
    unused_package_value = sum(
        (p.sessions_total - p.sessions_used) / p.sessions_total * (p.amount_paid or 0)
        for p in active_packages if p.sessions_total
    )

    return {
        "range": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        "totals": {
            "appointments": len(appointments),
            "conversations": total_convs,
            "expected_revenue": expected_revenue,
            "actual_revenue": actual_revenue,
            "ai_booked_appointments": ai_booked,
            "ledger_revenue": ledger_total,
            "ai_revenue": ai_revenue,
            "roi": roi,
            "monthly_fee": monthly_fee,
            "returning_patients": returning_patients,
            "active_packages": len(active_packages),
            "unused_package_value": unused_package_value,
        },
        "revenue_by_source": dict(revenue_by_source),
        "status_counts": dict(status_counts),
        "no_show_rate_percent": no_show_rate,
        "conversion_rate_percent": conversion_rate,
        "handoff_rate_percent": handoff_rate,
        "revenue_by_service": [
            {"name": name, **data} for name, data in
            sorted(revenue_by_service.items(), key=lambda x: -x[1]["revenue"])
        ],
        "revenue_by_doctor": [
            {"name": name, **data} for name, data in
            sorted(revenue_by_doctor.items(), key=lambda x: -x[1]["revenue"])
        ],
        "peak_hours": [{"hour": h, "count": c} for h, c in peak_hours.items()],
    }
