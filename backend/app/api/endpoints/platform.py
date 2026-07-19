"""
Platform super-admin (vendor/publisher) area. Lets the person who SELLS CareDesk AI
provision, price, suspend and monitor every clinic tenant from one place.
Guarded by is_platform_admin — normal clinic owners can never reach it.
"""
from datetime import datetime, timedelta
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.core.security import get_password_hash
from backend.app.api.deps import get_platform_admin
from backend.app.models.models import User, Clinic, Organization
from backend.app.schemas.schemas import (
    PlatformClinicCreate, PlatformClinicUpdate, OrganizationCreate, OrganizationOut
)
from backend.app.services.tenant_stats import clinic_metrics, aggregate
from backend.app.services.audit import log_action

router = APIRouter()

_PLAN_QUOTA = {"free": settings.PLAN_FREE_QUOTA, "pro": settings.PLAN_PRO_QUOTA}


def _seed_starter_catalogue(db: Session, clinic: Clinic) -> None:
    """A minimal, editable starting point so a brand-new tenant is demo-ready."""
    from backend.app.models.models import Branch, Service, Doctor, WorkingSchedule
    import datetime as _dt

    branch = Branch(clinic_id=clinic.id, name="Cơ sở chính", address=clinic.address or "Đang cập nhật",
                    phone=clinic.phone, working_hours="08:00 - 20:00")
    db.add(branch)
    db.flush()
    svc = Service(clinic_id=clinic.id, name="Khám & tư vấn da liễu", description="Khám và tư vấn với bác sĩ.",
                  price=150000, duration_minutes=30)
    db.add(svc)
    doc = Doctor(clinic_id=clinic.id, name="Bác sĩ phụ trách", specialty="Da liễu",
                 branch_id=branch.id, is_active=True)
    db.add(doc)
    db.flush()
    for day in range(6):  # Mon-Sat
        db.add(WorkingSchedule(doctor_id=doc.id, branch_id=branch.id, day_of_week=day,
                               start_time=_dt.time(8, 0), end_time=_dt.time(17, 0)))


@router.get("/overview")
def platform_overview(
    db: Session = Depends(get_db),
    _: User = Depends(get_platform_admin),
) -> Any:
    clinics = db.query(Clinic).all()
    metrics = [clinic_metrics(db, c) for c in clinics]
    totals = aggregate(metrics)
    totals["organizations"] = db.query(Organization).count()
    return {"totals": totals, "clinics": metrics}


@router.get("/clinics")
def list_clinics(
    db: Session = Depends(get_db),
    _: User = Depends(get_platform_admin),
) -> Any:
    return [clinic_metrics(db, c) for c in db.query(Clinic).order_by(Clinic.id.asc()).all()]


@router.post("/clinics")
def provision_clinic(
    body: PlatformClinicCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_platform_admin),
) -> Any:
    if db.query(User).filter(User.email == body.owner_email).first():
        raise HTTPException(400, "Email chủ phòng khám này đã tồn tại.")
    if body.plan not in _PLAN_QUOTA:
        raise HTTPException(400, "Gói không hợp lệ (free | pro).")
    if body.organization_id and not db.query(Organization).filter(Organization.id == body.organization_id).first():
        raise HTTPException(404, "Tổ chức/chuỗi không tồn tại.")

    clinic = Clinic(
        name=body.clinic_name, phone=body.phone, address=body.address,
        plan=body.plan, ai_quota_monthly=_PLAN_QUOTA[body.plan],
        monthly_fee=body.monthly_fee or 0.0, organization_id=body.organization_id,
        is_active=True,
    )
    db.add(clinic)
    db.flush()

    owner = User(
        clinic_id=clinic.id, email=body.owner_email,
        password_hash=get_password_hash(body.owner_password),
        full_name=body.owner_name, role="owner", is_active=True,
    )
    db.add(owner)

    if body.seed_demo_catalogue:
        _seed_starter_catalogue(db, clinic)

    log_action(db, admin.id, "provision_clinic",
               f"Nhà phát hành tạo phòng khám: {clinic.name} (gói {clinic.plan})")
    db.commit()

    from backend.app.services.events import seed_default_automations
    seed_default_automations(db, clinic.id)

    return clinic_metrics(db, clinic)


@router.patch("/clinics/{clinic_id}")
def update_clinic(
    clinic_id: int,
    body: PlatformClinicUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_platform_admin),
) -> Any:
    clinic = db.query(Clinic).filter(Clinic.id == clinic_id).first()
    if not clinic:
        raise HTTPException(404, "Phòng khám không tồn tại.")

    if body.plan is not None:
        if body.plan not in _PLAN_QUOTA:
            raise HTTPException(400, "Gói không hợp lệ (free | pro).")
        clinic.plan = body.plan
        # Reset quota to the plan default unless an explicit quota is also supplied
        if body.ai_quota_monthly is None:
            clinic.ai_quota_monthly = _PLAN_QUOTA[body.plan]
    if body.ai_quota_monthly is not None:
        clinic.ai_quota_monthly = body.ai_quota_monthly
    if body.monthly_fee is not None:
        clinic.monthly_fee = body.monthly_fee
    if body.is_active is not None:
        clinic.is_active = body.is_active
    if body.organization_id is not None:
        if body.organization_id == 0:
            clinic.organization_id = None
        else:
            if not db.query(Organization).filter(Organization.id == body.organization_id).first():
                raise HTTPException(404, "Tổ chức/chuỗi không tồn tại.")
            clinic.organization_id = body.organization_id

    log_action(db, admin.id, "update_clinic",
               f"Cập nhật phòng khám #{clinic.id}: plan={clinic.plan}, active={clinic.is_active}")
    db.commit()
    return clinic_metrics(db, clinic)


# ===== Organizations / chains =====
@router.get("/organizations")
def list_organizations(
    db: Session = Depends(get_db),
    _: User = Depends(get_platform_admin),
) -> Any:
    orgs = db.query(Organization).order_by(Organization.id.asc()).all()
    out = []
    for o in orgs:
        clinic_count = db.query(Clinic).filter(Clinic.organization_id == o.id).count()
        owner = db.query(User).filter(User.organization_id == o.id, User.role == "org_owner").first()
        out.append({"id": o.id, "name": o.name, "is_active": bool(o.is_active),
                    "clinic_count": clinic_count, "owner_email": owner.email if owner else None,
                    "created_at": o.created_at.isoformat() if o.created_at else None})
    return out


@router.post("/organizations", response_model=OrganizationOut)
def create_organization(
    body: OrganizationCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_platform_admin),
) -> Any:
    if db.query(User).filter(User.email == body.owner_email).first():
        raise HTTPException(400, "Email chủ chuỗi này đã tồn tại.")

    org = Organization(name=body.name, is_active=True)
    db.add(org)
    db.flush()

    # Chain owner: an account bound to the organization, not to a single clinic.
    owner = User(
        organization_id=org.id, clinic_id=None, email=body.owner_email,
        password_hash=get_password_hash(body.owner_password),
        full_name=body.owner_name, role="org_owner", is_active=True,
    )
    db.add(owner)
    log_action(db, admin.id, "create_organization", f"Tạo chuỗi phòng khám: {org.name}")
    db.commit()
    db.refresh(org)
    return org
