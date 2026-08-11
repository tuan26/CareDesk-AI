from datetime import date
from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend.app.core.database import get_db
from backend.app.api.deps import (
    verify_receptionist_or_above, verify_owner, get_current_active_user
)
from backend.app.models.models import (
    Clinic, Branch, Service, Doctor, DoctorTimeOff, WorkingSchedule, User,
    ChannelIntegration, AuditLog
)
from backend.app.schemas.schemas import (
    ClinicOut, ClinicCreate, BranchOut, BranchCreate, BranchUpdate,
    ServiceOut, ServiceCreate, DoctorOut, DoctorBase,
    WorkingScheduleOut, WorkingScheduleCreate,
    ChannelIntegrationIn, ChannelIntegrationOut, TimeOffBase, TimeOffOut
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
    current_user: User = Depends(verify_owner)
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
    current_user: User = Depends(verify_owner)
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
    current_user: User = Depends(verify_owner)
) -> Any:
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Không tìm thấy chi nhánh.")
    if current_user.clinic_id and branch.clinic_id != current_user.clinic_id:
        raise HTTPException(status_code=403, detail="Chi nhánh không thuộc phòng khám của bạn.")

    for field in ("name", "address", "phone", "working_hours", "map_url",
                  "latitude", "longitude", "landing_enabled", "is_active"):
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
    current_user: User = Depends(verify_owner)
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
    current_user: User = Depends(verify_owner)
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
    current_user: User = Depends(verify_owner)
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
    current_user: User = Depends(verify_owner)
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
    current_user: User = Depends(verify_owner)
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
    current_user: User = Depends(verify_owner)
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
    current_user: User = Depends(verify_owner)
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
    current_user: User = Depends(verify_owner)
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
    current_user: User = Depends(verify_owner)
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

# --- DOCTOR TIME OFF ---
# WorkingSchedule is the rule; this is the exception to it. Without it the AI
# takes bookings for doctors who are on leave and for days the clinic is shut.

@router.get("/time-off", response_model=List[TimeOffOut])
def list_time_off(
    upcoming_only: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    query = _scoped(db.query(DoctorTimeOff), DoctorTimeOff, current_user)
    if upcoming_only:
        query = query.filter(DoctorTimeOff.end_date >= date.today())
    rows = query.order_by(DoctorTimeOff.start_date).all()
    return [
        TimeOffOut(
            id=r.id, clinic_id=r.clinic_id, doctor_id=r.doctor_id,
            start_date=r.start_date, end_date=r.end_date,
            start_time=r.start_time, end_time=r.end_time, reason=r.reason,
            doctor_name=r.doctor.name if r.doctor else "Cả phòng khám",
        ) for r in rows
    ]


@router.post("/time-off", response_model=TimeOffOut)
def create_time_off(
    body: TimeOffBase,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner)
) -> Any:
    if body.end_date < body.start_date:
        raise HTTPException(status_code=400, detail="Ngày kết thúc phải sau ngày bắt đầu.")
    # Half day needs both ends: one alone cannot describe a block of time, and
    # silently treating it as a full day would hide bookable hours.
    if (body.start_time is None) != (body.end_time is None):
        raise HTTPException(
            status_code=400,
            detail="Nghỉ nửa ngày phải nhập cả giờ bắt đầu và giờ kết thúc. "
                   "Bỏ trống cả hai nghĩa là nghỉ cả ngày.")
    if body.start_time and body.end_time and body.end_time <= body.start_time:
        raise HTTPException(status_code=400, detail="Giờ kết thúc phải sau giờ bắt đầu.")

    if body.doctor_id:
        doctor = db.query(Doctor).filter(Doctor.id == body.doctor_id).first()
        if not doctor:
            raise HTTPException(status_code=404, detail="Không tìm thấy bác sĩ.")
        _check_same_clinic(doctor.clinic_id, current_user)

    row = DoctorTimeOff(clinic_id=current_user.clinic_id, **body.model_dump())
    db.add(row)
    who = row.doctor.name if row.doctor_id else "cả phòng khám"
    log_action(db, current_user.id, "create_time_off",
               f"Nghỉ: {who} từ {body.start_date} đến {body.end_date}")
    db.commit()
    db.refresh(row)
    return TimeOffOut(
        id=row.id, clinic_id=row.clinic_id, doctor_id=row.doctor_id,
        start_date=row.start_date, end_date=row.end_date,
        start_time=row.start_time, end_time=row.end_time, reason=row.reason,
        doctor_name=row.doctor.name if row.doctor else "Cả phòng khám",
    )


@router.delete("/time-off/{off_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_time_off(
    off_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner)
):
    row = db.query(DoctorTimeOff).filter(DoctorTimeOff.id == off_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Không tìm thấy lịch nghỉ.")
    _check_same_clinic(row.clinic_id, current_user)
    log_action(db, current_user.id, "delete_time_off", f"Xoá lịch nghỉ #{off_id}")
    db.delete(row)
    db.commit()
    return


@router.get("/features")
def get_features(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """Which optional areas are on for this clinic. Readable by any signed-in
    user because the frontend needs it to decide what to render in the nav."""
    from backend.app.services.features import LABELS, all_flags

    flags = all_flags(db, current_user.clinic_id)
    return {"flags": flags,
            "labels": {k: LABELS.get(k, k) for k in flags}}


@router.put("/features/{key}")
def set_feature(
    key: str,
    enabled: bool,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner)
) -> Any:
    from backend.app.services.features import set_flag

    try:
        set_flag(db, current_user.clinic_id, key, enabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    log_action(db, current_user.id, "set_feature_flag", f"{key} -> {enabled}")
    db.commit()
    return {"key": key, "enabled": enabled}


@router.get("/readiness")
def get_readiness(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    """What still stops this clinic from doing the two things we sell.

    One source of truth for three consumers: the dashboard banner, the
    onboarding wizard's progress, and the guard that refuses to publish a public
    link. Keeping them in sync any other way guarantees they drift.
    """
    from backend.app.services.channel_gateway import outbound_status

    cid = current_user.clinic_id
    clinic = db.query(Clinic).filter(Clinic.id == cid).first() if cid else None

    has_service = db.query(Service).filter(Service.clinic_id == cid).first() is not None
    has_doctor = db.query(Doctor).filter(
        Doctor.clinic_id == cid, Doctor.is_active == True  # noqa: E712
    ).first() is not None
    # A schedule is what turns doctors into bookable slots. Without one the AI
    # answers every booking attempt with "hiện chưa có khung giờ trống".
    has_schedule = db.query(WorkingSchedule).join(
        Doctor, WorkingSchedule.doctor_id == Doctor.id
    ).filter(Doctor.clinic_id == cid).first() is not None
    has_hours = bool(clinic and (clinic.address or "").strip())

    channels = outbound_status(db, cid)

    blockers = []
    if not has_service:
        blockers.append({"code": "no_service", "severity": "critical",
                         "message": "Chưa có dịch vụ nào — AI không có gì để báo giá.",
                         "action": "/services"})
    if not has_doctor:
        blockers.append({"code": "no_doctor", "severity": "critical",
                         "message": "Chưa có bác sĩ đang hoạt động.",
                         "action": "/doctors"})
    if not has_schedule:
        blockers.append({"code": "no_schedule", "severity": "critical",
                         "message": "Chưa có lịch làm việc — AI không thể chốt được lịch hẹn nào.",
                         "action": "/doctors"})
    # Phone channel. A simulated one (Zalo Test OA, SMS sandbox/mock) gets its
    # own message rather than the generic "not configured": the integration IS
    # working, which is a different problem from nothing being set up, and the
    # difference decides what the clinic should do next.
    if channels.get("zns_simulated") or channels.get("sms_simulated"):
        blockers.append({
            "code": "simulated_channel", "severity": "critical",
            "message": "Đang chạy kênh THỬ NGHIỆM (Zalo OA Test / SMS sandbox). "
                       "Tích hợp hoạt động, nhưng tin nhắn KHÔNG tới bệnh nhân thật. "
                       "Phải chuyển sang OA thật hoặc SMS thật trước khi nhận khách.",
            "action": "/settings"})
    elif not channels["can_reach_phone"]:
        message = ("Chưa kết nối Zalo (ZNS/Template Message) hoặc SMS — "
                   "tin nhắn nhắc lịch KHÔNG được gửi đi.")
        if channels["email"]:
            # Email works, so reminders are not entirely dead — but saying
            # "reminders are on" here would be misleading: Vietnamese patients
            # overwhelmingly do not read email appointment reminders.
            message = ("Mới chỉ nhắc lịch được qua email. Chưa kết nối Zalo "
                       "hoặc SMS, mà phần lớn bệnh nhân không đọc email nhắc lịch.")
        blockers.append({"code": "no_phone_channel", "severity": "critical",
                         "message": message, "action": "/settings"})

    if not channels["email"]:
        blockers.append({"code": "no_email", "severity": "warning",
                         "message": "Chưa cấu hình email — không gửi được xác nhận qua email.",
                         "action": "/settings"})

    return {
        "has_service": has_service,
        "has_doctor": has_doctor,
        "has_schedule": has_schedule,
        "has_address": has_hours,
        "channels": channels,
        # Everything needed to take a real booking end to end.
        "can_take_bookings": has_service and has_doctor and has_schedule,
        "can_send_reminders": channels["can_reach_phone"],
        "blockers": blockers,
    }


@router.get("/channels", response_model=List[ChannelIntegrationOut])
def get_channels(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner)
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
    current_user: User = Depends(verify_owner)
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
    current_user: User = Depends(verify_owner)
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
