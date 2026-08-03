from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend.app.core.database import get_db
from backend.app.api.deps import (
    verify_receptionist_or_above, verify_owner_or_admin, get_current_active_user
)
from backend.app.models.models import (
    Clinic, Branch, Service, Doctor, WorkingSchedule, User, ChannelIntegration, AuditLog
)
from backend.app.schemas.schemas import (
    ClinicOut, ClinicCreate, BranchOut, BranchCreate, BranchUpdate,
    ServiceOut, ServiceCreate, DoctorOut, DoctorBase,
    WorkingScheduleOut, WorkingScheduleCreate,
    ChannelIntegrationIn, ChannelIntegrationOut
)
from backend.app.core.slug import assign_slug, change_slug
from backend.app.services.audit import log_action

router = APIRouter()


def _scoped(query, model, user: User):
    """Restrict a query to the current user's clinic (multi-tenant isolation)."""
    if user.clinic_id:
        return query.filter(model.clinic_id == user.clinic_id)
    return query  # system-level account (no clinic bound): sees everything


def _check_same_clinic(obj_clinic_id, user: User):
    if user.clinic_id and obj_clinic_id and obj_clinic_id != user.clinic_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Dữ liệu không thuộc phòng khám của bạn.")


# --- CLINIC ---
@router.get("", response_model=List[ClinicOut])
def get_clinics(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    query = db.query(Clinic)
    if current_user.clinic_id:
        query = query.filter(Clinic.id == current_user.clinic_id)
    return query.all()

@router.put("/{clinic_id}", response_model=ClinicOut)
def update_clinic(
    clinic_id: int,
    clinic_in: ClinicCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
) -> Any:
    clinic = db.query(Clinic).filter(Clinic.id == clinic_id).first()
    if not clinic:
        raise HTTPException(status_code=404, detail="Không tìm thấy phòng khám")
    _check_same_clinic(clinic.id, current_user)

    # exclude_unset: partial updates must not wipe fields the caller didn't send
    for key, value in clinic_in.model_dump(exclude_unset=True).items():
        setattr(clinic, key, value)

    log_action(db, current_user.id, "update_clinic", f"Cập nhật hồ sơ phòng khám #{clinic.id}")
    db.commit()
    db.refresh(clinic)
    return clinic


# --- BRANCHES ---
@router.get("/branches", response_model=List[BranchOut])
def get_branches(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    return _scoped(db.query(Branch), Branch, current_user).all()

@router.post("/branches", response_model=BranchOut)
def create_branch(
    branch_in: BranchCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
) -> Any:
    data = branch_in.model_dump()
    if current_user.clinic_id:
        data["clinic_id"] = current_user.clinic_id
    db_branch = Branch(**data)
    db.add(db_branch)
    db.flush()
    assign_slug(db, db_branch)  # public URL is allocated up front, before landing is enabled
    log_action(db, current_user.id, "create_branch", f"Thêm chi nhánh: {db_branch.name}")
    db.commit()
    db.refresh(db_branch)
    return db_branch


@router.patch("/branches/{branch_id}", response_model=BranchOut)
def update_branch(
    branch_id: int,
    body: BranchUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
) -> Any:
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Không tìm thấy chi nhánh.")
    if current_user.clinic_id and branch.clinic_id != current_user.clinic_id:
        raise HTTPException(status_code=403, detail="Chi nhánh không thuộc phòng khám của bạn.")

    for field in ("name", "address", "phone", "working_hours", "landing_enabled", "is_active"):
        value = getattr(body, field)
        if value is not None:
            setattr(branch, field, value)

    # Changing the public URL is an explicit, separate action: renaming the
    # branch above leaves the slug (and every printed QR code) untouched.
    if body.slug is not None and body.slug != branch.slug:
        try:
            change_slug(db, branch, body.slug)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    log_action(db, current_user.id, "update_branch", f"Cập nhật chi nhánh: {branch.name}")
    db.commit()
    db.refresh(branch)
    return branch

@router.delete("/branches/{branch_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_branch(
    branch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
):
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Không tìm thấy chi nhánh")
    _check_same_clinic(branch.clinic_id, current_user)
    log_action(db, current_user.id, "delete_branch", f"Xóa chi nhánh: {branch.name} (#{branch.id})")
    db.delete(branch)
    db.commit()
    return


# --- SERVICES ---
@router.get("/services", response_model=List[ServiceOut])
def get_services(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    return _scoped(db.query(Service), Service, current_user).all()

@router.post("/services", response_model=ServiceOut)
def create_service(
    service_in: ServiceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
) -> Any:
    data = service_in.model_dump()
    if current_user.clinic_id:
        data["clinic_id"] = current_user.clinic_id
    db_service = Service(**data)
    db.add(db_service)
    log_action(db, current_user.id, "create_service", f"Thêm dịch vụ: {db_service.name}")
    db.commit()
    db.refresh(db_service)
    return db_service

@router.put("/services/{service_id}", response_model=ServiceOut)
def update_service(
    service_id: int,
    service_in: ServiceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
) -> Any:
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Không tìm thấy dịch vụ")
    _check_same_clinic(service.clinic_id, current_user)

    data = service_in.model_dump()
    data.pop("clinic_id", None)  # tenant of a service never changes
    for key, value in data.items():
        setattr(service, key, value)

    log_action(db, current_user.id, "update_service", f"Cập nhật dịch vụ: {service.name} (#{service.id})")
    db.commit()
    db.refresh(service)
    return service

@router.delete("/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_service(
    service_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
):
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Không tìm thấy dịch vụ")
    _check_same_clinic(service.clinic_id, current_user)
    log_action(db, current_user.id, "delete_service", f"Xóa dịch vụ: {service.name} (#{service.id})")
    db.delete(service)
    db.commit()
    return


# --- DOCTORS ---
@router.get("/doctors", response_model=List[DoctorOut])
def get_doctors(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    return _scoped(db.query(Doctor), Doctor, current_user).all()

@router.post("/doctors", response_model=DoctorOut)
def create_doctor(
    doctor_in: DoctorBase,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
) -> Any:
    db_doctor = Doctor(**doctor_in.model_dump(), clinic_id=current_user.clinic_id)
    db.add(db_doctor)
    log_action(db, current_user.id, "create_doctor", f"Thêm bác sĩ: {db_doctor.name}")
    db.commit()
    db.refresh(db_doctor)
    return db_doctor

@router.put("/doctors/{doctor_id}", response_model=DoctorOut)
def update_doctor(
    doctor_id: int,
    doctor_in: DoctorBase,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
) -> Any:
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Không tìm thấy bác sĩ")
    _check_same_clinic(doctor.clinic_id, current_user)

    for key, value in doctor_in.model_dump().items():
        setattr(doctor, key, value)

    log_action(db, current_user.id, "update_doctor", f"Cập nhật bác sĩ: {doctor.name} (#{doctor.id})")
    db.commit()
    db.refresh(doctor)
    return doctor

@router.delete("/doctors/{doctor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_doctor(
    doctor_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Không tìm thấy bác sĩ")
    _check_same_clinic(doctor.clinic_id, current_user)
    log_action(db, current_user.id, "delete_doctor", f"Xóa bác sĩ: {doctor.name} (#{doctor.id})")
    db.delete(doctor)
    db.commit()
    return


# --- SCHEDULES ---
@router.get("/schedules", response_model=List[WorkingScheduleOut])
def get_schedules(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    query = db.query(WorkingSchedule)
    if current_user.clinic_id:
        query = query.join(Doctor, WorkingSchedule.doctor_id == Doctor.id).filter(
            Doctor.clinic_id == current_user.clinic_id
        )
    return query.all()

@router.post("/schedules", response_model=WorkingScheduleOut)
def create_schedule(
    schedule_in: WorkingScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
) -> Any:
    doc = db.query(Doctor).filter(Doctor.id == schedule_in.doctor_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Không tìm thấy bác sĩ")
    _check_same_clinic(doc.clinic_id, current_user)
    branch = db.query(Branch).filter(Branch.id == schedule_in.branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Không tìm thấy chi nhánh")

    db_sched = WorkingSchedule(**schedule_in.model_dump())
    db.add(db_sched)
    log_action(db, current_user.id, "create_schedule", f"Xếp ca cho bác sĩ #{doc.id}")
    db.commit()
    db.refresh(db_sched)
    return db_sched

@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
):
    sched = db.query(WorkingSchedule).filter(WorkingSchedule.id == schedule_id).first()
    if not sched:
        raise HTTPException(status_code=404, detail="Không tìm thấy lịch làm việc")
    doc = db.query(Doctor).filter(Doctor.id == sched.doctor_id).first()
    if doc:
        _check_same_clinic(doc.clinic_id, current_user)
    log_action(db, current_user.id, "delete_schedule", f"Xóa ca làm việc #{sched.id}")
    db.delete(sched)
    db.commit()
    return


# --- CHANNEL INTEGRATIONS (Zalo OA / Facebook Messenger) ---
def _mask(token: str) -> str:
    if not token:
        return None
    return f"••••{token[-4:]}" if len(token) > 4 else "••••"

@router.get("/channels", response_model=List[ChannelIntegrationOut])
def get_channels(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
) -> Any:
    integrations = db.query(ChannelIntegration).filter(
        ChannelIntegration.clinic_id == (current_user.clinic_id or 0)
    ).all()
    return [
        ChannelIntegrationOut(
            id=i.id, channel=i.channel, enabled=i.enabled,
            access_token_masked=_mask(i.access_token),
            verify_token=i.verify_token, extra_config=i.extra_config
        ) for i in integrations
    ]

@router.post("/channels", response_model=ChannelIntegrationOut)
def upsert_channel(
    channel_in: ChannelIntegrationIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
) -> Any:
    if channel_in.channel not in ("zalo", "facebook"):
        raise HTTPException(status_code=400, detail="Kênh không hợp lệ (zalo | facebook)")
    if not current_user.clinic_id:
        raise HTTPException(status_code=400, detail="Tài khoản chưa gắn với phòng khám nào.")

    integration = db.query(ChannelIntegration).filter(
        ChannelIntegration.clinic_id == current_user.clinic_id,
        ChannelIntegration.channel == channel_in.channel
    ).first()
    if not integration:
        integration = ChannelIntegration(clinic_id=current_user.clinic_id, channel=channel_in.channel)
        db.add(integration)

    integration.enabled = channel_in.enabled
    if channel_in.access_token:  # keep old token when field left blank
        integration.access_token = channel_in.access_token
    if channel_in.verify_token is not None:
        integration.verify_token = channel_in.verify_token
    if channel_in.extra_config is not None:
        integration.extra_config = channel_in.extra_config

    log_action(db, current_user.id, "update_channel", f"Cấu hình kênh {channel_in.channel} (enabled={channel_in.enabled})")
    db.commit()
    db.refresh(integration)
    return ChannelIntegrationOut(
        id=integration.id, channel=integration.channel, enabled=integration.enabled,
        access_token_masked=_mask(integration.access_token),
        verify_token=integration.verify_token, extra_config=integration.extra_config
    )


# --- AUDIT LOGS ---
@router.get("/audit-logs")
def get_audit_logs(
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
) -> Any:
    query = db.query(AuditLog, User).outerjoin(User, AuditLog.user_id == User.id)
    if current_user.clinic_id:
        query = query.filter((User.clinic_id == current_user.clinic_id) | (AuditLog.user_id == None))  # noqa: E711
    rows = query.order_by(AuditLog.created_at.desc()).limit(min(limit, 500)).all()
    return [
        {
            "id": log.id,
            "action": log.action,
            "details": log.details,
            "user_email": user.email if user else None,
            "user_name": user.full_name if user else "Hệ thống",
            "created_at": log.created_at
        }
        for log, user in rows
    ]
