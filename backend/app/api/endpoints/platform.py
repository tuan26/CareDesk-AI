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
from backend.app.core.slug import assign_slug, change_slug
from backend.app.api.deps import get_platform_admin
from backend.app.models.models import User, Clinic, Organization, Plan
from backend.app.schemas.schemas import (
    PlatformClinicCreate, PlatformClinicUpdate, OrganizationCreate, OrganizationOut,
    OrganizationUpdate,
    PlanCreate, PlanUpdate, PlanOut
)
from backend.app.services.tenant_stats import clinic_metrics, aggregate
from backend.app.services.audit import log_action
from backend.app.core import clock

router = APIRouter()


def _resolve_plan(db: Session, plan_id: Optional[int], plan_code: Optional[str]) -> Optional[Plan]:
    if plan_id:
        return db.query(Plan).filter(Plan.id == plan_id).first()
    if plan_code:
        return db.query(Plan).filter(Plan.code == plan_code).first()
    return db.query(Plan).filter(Plan.code == "free").first()


def _apply_plan(clinic: Clinic, plan: Plan, fee_override: Optional[float] = None) -> None:
    """Set a clinic's quota/fee/trial from a plan row."""
    clinic.plan_id = plan.id
    clinic.plan = plan.code
    clinic.ai_quota_monthly = plan.monthly_quota
    clinic.monthly_fee = fee_override if fee_override is not None else plan.price
    if plan.trial_days and plan.trial_days > 0:
        clinic.trial_ends_at = clock.now() + timedelta(days=plan.trial_days)
    else:
        clinic.trial_ends_at = None


def _seed_starter_catalogue(db: Session, clinic: Clinic) -> None:
    """A minimal, editable starting point so a brand-new tenant is demo-ready."""
    from backend.app.models.models import Branch, Service, Doctor, WorkingSchedule
    import datetime as _dt

    branch = Branch(clinic_id=clinic.id, name="Cơ sở chính", address=clinic.address or "Đang cập nhật",
                    phone=clinic.phone, working_hours="08:00 - 20:00")
    db.add(branch)
    db.flush()
    assign_slug(db, branch)
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
    plan = _resolve_plan(db, body.plan_id, body.plan)
    if not plan:
        raise HTTPException(400, "Gói cước không hợp lệ hoặc chưa được cấu hình.")
    org_id = body.organization_id
    if org_id:
        if not db.query(Organization).filter(Organization.id == org_id).first():
            raise HTTPException(404, "Tổ chức/chuỗi không tồn tại.")
    else:
        # Every clinic lives under an organization. A standalone partner gets a
        # personal org (its own brand) so the /org/<org>/clinics/<clinic> URL is uniform.
        personal = Organization(name=body.clinic_name, is_active=True)
        db.add(personal)
        db.flush()
        assign_slug(db, personal)
        org_id = personal.id

    clinic = Clinic(
        name=body.clinic_name, phone=body.phone, address=body.address,
        organization_id=org_id, is_active=True,
    )
    _apply_plan(clinic, plan, fee_override=body.monthly_fee)
    db.add(clinic)
    db.flush()
    assign_slug(db, clinic)

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

    # Plan change: re-derive quota/fee/trial from the new plan
    if body.plan_id is not None:
        plan = db.query(Plan).filter(Plan.id == body.plan_id).first()
        if not plan:
            raise HTTPException(404, "Gói cước không tồn tại.")
        _apply_plan(clinic, plan, fee_override=body.monthly_fee)

    # Profile fields
    if body.name is not None:
        clinic.name = body.name
    if body.phone is not None:
        clinic.phone = body.phone
    if body.address is not None:
        clinic.address = body.address
    if body.logo_url is not None:
        clinic.logo_url = body.logo_url
    if body.og_image_url is not None:
        clinic.og_image_url = body.og_image_url
    if body.slug is not None:
        # No-op when unchanged: a public URL must never churn just because the
        # edit form resubmitted the same slug. The old slug stays registered for
        # a 301 when it does change.
        try:
            change_slug(db, clinic, body.slug)
        except ValueError as e:
            raise HTTPException(400, str(e))

    # Overrides (allowed even without a plan change)
    if body.ai_quota_monthly is not None:
        clinic.ai_quota_monthly = body.ai_quota_monthly
    if body.monthly_fee is not None:
        clinic.monthly_fee = body.monthly_fee
    if body.trial_ends_at is not None:
        clinic.trial_ends_at = body.trial_ends_at
    if body.is_active is not None:
        clinic.is_active = body.is_active
    if body.landing_enabled is not None:
        clinic.landing_enabled = body.landing_enabled
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


# ===== Subscription plans =====
@router.get("/plans", response_model=list[PlanOut])
def list_plans(db: Session = Depends(get_db), _: User = Depends(get_platform_admin)) -> Any:
    return db.query(Plan).order_by(Plan.price.asc()).all()


@router.post("/plans", response_model=PlanOut)
def create_plan(body: PlanCreate, db: Session = Depends(get_db),
                admin: User = Depends(get_platform_admin)) -> Any:
    from backend.app.core.slug import slugify
    code = slugify(body.code)
    if not code:
        raise HTTPException(400, "Mã gói không hợp lệ.")
    if db.query(Plan).filter(Plan.code == code).first():
        raise HTTPException(400, "Mã gói đã tồn tại.")
    plan = Plan(code=code, name=body.name, monthly_quota=body.monthly_quota,
                price=body.price, trial_days=body.trial_days, is_active=body.is_active)
    db.add(plan)
    log_action(db, admin.id, "create_plan", f"Tạo gói cước: {plan.name} ({plan.code})")
    db.commit()
    db.refresh(plan)
    return plan


@router.patch("/plans/{plan_id}", response_model=PlanOut)
def update_plan(plan_id: int, body: PlanUpdate, db: Session = Depends(get_db),
                admin: User = Depends(get_platform_admin)) -> Any:
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "Gói cước không tồn tại.")
    for field in ("name", "monthly_quota", "price", "trial_days", "is_active"):
        val = getattr(body, field)
        if val is not None:
            setattr(plan, field, val)
    log_action(db, admin.id, "update_plan", f"Cập nhật gói cước #{plan.id}: {plan.name}")
    db.commit()
    db.refresh(plan)
    return plan


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
        out.append({"id": o.id, "name": o.name, "slug": o.slug, "is_active": bool(o.is_active),
                    "landing_enabled": bool(o.landing_enabled),
                    "clinic_count": clinic_count, "owner_email": owner.email if owner else None,
                    "created_at": o.created_at.isoformat() if o.created_at else None})
    return out


@router.patch("/organizations/{org_id}", response_model=OrganizationOut)
def update_organization(
    org_id: int,
    body: OrganizationUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_platform_admin),
) -> Any:
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(404, "Chuỗi không tồn tại.")

    if body.name is not None:
        org.name = body.name
    if body.is_active is not None:
        org.is_active = body.is_active
    if body.landing_enabled is not None:
        org.landing_enabled = body.landing_enabled
    if body.slug is not None:
        # Same rule as clinics: renaming leaves the public URL alone, moving it
        # is explicit and the old slug stays registered for a 301.
        try:
            change_slug(db, org, body.slug)
        except ValueError as e:
            raise HTTPException(400, str(e))

    log_action(db, admin.id, "update_organization", f"Cập nhật chuỗi: {org.name}")
    db.commit()
    db.refresh(org)
    return org


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
    assign_slug(db, org)
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
