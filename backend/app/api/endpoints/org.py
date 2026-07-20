"""
Organization / chain owner area. A chain owner logs in with an org_owner account
and sees an aggregated roll-up across every clinic under their organization —
"hôm nay cả chuỗi có bao nhiêu bệnh nhân, doanh thu thế nào" across branches.
Read-only: managing a single clinic still happens inside that clinic's dashboard.
"""
from datetime import timedelta
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.core.security import create_access_token
from backend.app.api.deps import get_org_user
from backend.app.models.models import User, Clinic, Organization
from backend.app.schemas.schemas import Token
from backend.app.services.tenant_stats import clinic_metrics, aggregate

router = APIRouter()


@router.post("/enter-clinic/{clinic_id}", response_model=Token)
def enter_clinic(
    clinic_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_org_user),
) -> Any:
    """
    Chain owner steps into one of their clinics: returns a scoped token that grants
    owner-level access to THAT clinic only (verified to belong to the owner's chain).
    The frontend swaps this token in to reuse the full clinic dashboard.
    """
    clinic = db.query(Clinic).filter(
        Clinic.id == clinic_id, Clinic.organization_id == user.organization_id
    ).first()
    if not clinic:
        raise HTTPException(404, "Phòng khám không thuộc chuỗi của bạn.")
    token = create_access_token(
        user.email,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        extra_claims={"act_clinic_id": clinic.id},
    )
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me")
def my_organization(
    db: Session = Depends(get_db),
    user: User = Depends(get_org_user),
) -> Any:
    org = db.query(Organization).filter(Organization.id == user.organization_id).first()
    return {"id": org.id, "name": org.name, "slug": org.slug, "is_active": bool(org.is_active)} if org else None


@router.get("/overview")
def org_overview(
    db: Session = Depends(get_db),
    user: User = Depends(get_org_user),
) -> Any:
    clinics = db.query(Clinic).filter(Clinic.organization_id == user.organization_id).all()
    metrics = [clinic_metrics(db, c) for c in clinics]
    return {"totals": aggregate(metrics), "clinics": metrics}
