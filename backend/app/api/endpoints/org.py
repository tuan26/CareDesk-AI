"""
Organization / chain owner area. A chain owner logs in with an org_owner account
and sees an aggregated roll-up across every clinic under their organization —
"hôm nay cả chuỗi có bao nhiêu bệnh nhân, doanh thu thế nào" across branches.
Read-only: managing a single clinic still happens inside that clinic's dashboard.
"""
from typing import Any
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.app.core.database import get_db
from backend.app.api.deps import get_org_user
from backend.app.models.models import User, Clinic, Organization
from backend.app.services.tenant_stats import clinic_metrics, aggregate

router = APIRouter()


@router.get("/me")
def my_organization(
    db: Session = Depends(get_db),
    user: User = Depends(get_org_user),
) -> Any:
    org = db.query(Organization).filter(Organization.id == user.organization_id).first()
    return {"id": org.id, "name": org.name, "is_active": bool(org.is_active)} if org else None


@router.get("/overview")
def org_overview(
    db: Session = Depends(get_db),
    user: User = Depends(get_org_user),
) -> Any:
    clinics = db.query(Clinic).filter(Clinic.organization_id == user.organization_id).all()
    metrics = [clinic_metrics(db, c) for c in clinics]
    return {"totals": aggregate(metrics), "clinics": metrics}
