"""
Cross-tenant metrics used by the platform super-admin (vendor view) and the
organization/chain owner roll-up. One clinic's numbers are computed here so both
callers stay consistent with the per-clinic Reports screen.
"""
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session
from backend.app.models.models import (
    Clinic, PatientLead, Appointment, Conversation, RevenueRecord, User
)


def _month_start(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def clinic_metrics(db: Session, clinic: Clinic, since: Optional[datetime] = None) -> dict:
    """Snapshot for one clinic. `since` bounds revenue/appointments (default: this month)."""
    since = since or _month_start()

    patients = db.query(PatientLead).filter(PatientLead.clinic_id == clinic.id).count()

    appts = db.query(Appointment).filter(
        Appointment.clinic_id == clinic.id,
        Appointment.created_at >= since,
    ).all()
    appts_count = len(appts)
    completed = sum(1 for a in appts if a.status == "completed")

    ledger = db.query(RevenueRecord).filter(
        RevenueRecord.clinic_id == clinic.id,
        RevenueRecord.recorded_at >= since,
    ).all()
    revenue = sum(r.amount for r in ledger)
    ai_revenue = sum(r.amount for r in ledger if (r.source or "").startswith("ai_"))

    convs = db.query(Conversation).filter(
        Conversation.clinic_id == clinic.id,
        Conversation.created_at >= since,
    ).count()

    owner = db.query(User).filter(
        User.clinic_id == clinic.id, User.role == "owner"
    ).first()

    return {
        "clinic_id": clinic.id,
        "name": clinic.name,
        "slug": clinic.slug,
        "plan": clinic.plan,
        "plan_id": clinic.plan_id,
        "trial_ends_at": clinic.trial_ends_at.isoformat() if clinic.trial_ends_at else None,
        "is_active": bool(clinic.is_active),
        "organization_id": clinic.organization_id,
        "org_slug": clinic.organization.slug if clinic.organization else None,
        "og_image_url": clinic.og_image_url,
        "monthly_fee": clinic.monthly_fee or 0.0,
        "ai_quota_monthly": clinic.ai_quota_monthly,
        "owner_email": owner.email if owner else None,
        "patients": patients,
        "appointments_this_period": appts_count,
        "completed_this_period": completed,
        "revenue_this_period": revenue,
        "ai_revenue_this_period": ai_revenue,
        "conversations_this_period": convs,
        "created_at": clinic.created_at.isoformat() if clinic.created_at else None,
    }


def aggregate(metrics: List[dict], total_clinics: Optional[int] = None) -> dict:
    """Roll a list of clinic_metrics() up into platform/organization totals."""
    active = [m for m in metrics if m["is_active"]]
    return {
        "clinics": total_clinics if total_clinics is not None else len(metrics),
        "active_clinics": len(active),
        "suspended_clinics": len(metrics) - len(active),
        "mrr": sum(m["monthly_fee"] for m in active),  # monthly recurring revenue (vendor income)
        "total_patients": sum(m["patients"] for m in metrics),
        "revenue_this_period": sum(m["revenue_this_period"] for m in metrics),
        "ai_revenue_this_period": sum(m["ai_revenue_this_period"] for m in metrics),
        "appointments_this_period": sum(m["appointments_this_period"] for m in metrics),
        "conversations_this_period": sum(m["conversations_this_period"] for m in metrics),
    }
