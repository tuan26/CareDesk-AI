import logging
from typing import Any, List, Optional
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from backend.app.core.database import get_db
from backend.app.core.config import settings
from backend.app.api.deps import verify_receptionist_or_above, verify_owner
from backend.app.models.models import (
    Appointment, PatientLead, Service, Doctor, Branch, User, Conversation
)
from backend.app.schemas.schemas import (
    AppointmentOut, AppointmentCreate, PatientLeadOut, PatientLeadCreate,
    PatientLeadUpdate, PatientDetailOut
)
from backend.app.services.ai_engine import get_available_slots
from backend.app.services.audit import log_action
from backend.app.services.events import emit_event

logger = logging.getLogger(__name__)

router = APIRouter()


def handle_status_transition(db: Session, appt: Appointment, old_status: str):
    """
    Fire domain events + revenue ledger on appointment status changes.
    completed -> revenue record (or package session burn) + recall/review automations
    cancelled -> waitlist auto-fill kicks in
    """
    from backend.app.models.models import RevenueRecord, PatientPackage

    if old_status == appt.status:
        return
    service = appt.service
    payload = {
        "appointment_id": appt.id,
        "service_id": appt.service_id,
        "service_name": service.name if service else "",
        "slot": appt.start_time.strftime("%H:%M"),
        "date": appt.start_time.strftime("%d/%m/%Y"),
    }

    if appt.status == "completed":
        # Prefer burning a prepaid package session over billing the visit
        pkg = db.query(PatientPackage).join(
            PatientPackage.package
        ).filter(
            PatientPackage.patient_id == appt.patient_id,
            PatientPackage.status == "active"
        ).all()
        matching = next(
            (p for p in pkg
             if p.package and (p.package.service_id is None or p.package.service_id == appt.service_id)
             and (p.expires_at is None or p.expires_at.replace(tzinfo=None) >= datetime.now())),
            None
        )
        if matching:
            matching.sessions_used += 1
            if matching.sessions_used >= matching.sessions_total:
                matching.status = "used_up"
                emit_event(db, appt.clinic_id, "package_used_up", patient_id=appt.patient_id,
                           payload={"service_name": matching.package.name if matching.package else "gói liệu trình"})
            # revenue was recognized when the package was sold - no double count
        else:
            db.add(RevenueRecord(
                clinic_id=appt.clinic_id, patient_id=appt.patient_id, appointment_id=appt.id,
                amount=service.price if service else 0.0, source=appt.booking_source or "staff"
            ))
        emit_event(db, appt.clinic_id, "appointment_completed", patient_id=appt.patient_id, payload=payload)

    elif appt.status == "cancelled":
        emit_event(db, appt.clinic_id, "appointment_cancelled", patient_id=appt.patient_id, payload=payload)

    elif appt.status == "no_show":
        emit_event(db, appt.clinic_id, "appointment_no_show", patient_id=appt.patient_id, payload=payload)


def _scoped(query, model, user: User):
    if user.clinic_id:
        return query.filter(model.clinic_id == user.clinic_id)
    return query


def _check_same_clinic(obj_clinic_id, user: User):
    if user.clinic_id and obj_clinic_id and obj_clinic_id != user.clinic_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Dữ liệu không thuộc phòng khám của bạn.")


async def send_email_notification(to_email: str, subject: str, html_content: str) -> bool:
    """Send one email. Returns True only if it was actually accepted by the SMTP
    server, so callers can tell a real delivery from an unconfigured mailbox and
    avoid recording a delivery that never happened."""
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning("SMTP chưa cấu hình - email tới %s KHÔNG được gửi (%s)",
                       to_email, subject)
        return False

    message = MIMEMultipart("alternative")
    message["From"] = f"{settings.EMAILS_FROM_NAME} <{settings.EMAILS_FROM_EMAIL}>"
    message["To"] = to_email
    message["Subject"] = subject
    message.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        await aiosmtplib.send(
            message,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            use_tls=True if settings.SMTP_PORT == 465 else False,
            start_tls=True if settings.SMTP_PORT == 587 else False
        )
        logger.info("Đã gửi email tới %s", to_email)
        return True
    except Exception:
        logger.exception("Không gửi được email tới %s", to_email)
        return False


# --- PATIENT LEADS (mini-CRM; declared before /{appt_id} routes) ---
@router.get("/patients", response_model=List[PatientLeadOut])
def get_patients(
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    query = _scoped(db.query(PatientLead), PatientLead, current_user)
    if search:
        like = f"%{search}%"
        query = query.filter((PatientLead.full_name.ilike(like)) | (PatientLead.phone.ilike(like)))
    return query.order_by(PatientLead.created_at.desc()).all()


@router.post("/patients", response_model=PatientLeadOut)
def create_patient(
    lead_in: PatientLeadCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    if lead_in.phone:
        existing = _scoped(db.query(PatientLead), PatientLead, current_user).filter(
            PatientLead.phone == lead_in.phone
        ).first()
        if existing:
            return existing

    data = lead_in.model_dump()
    data.pop("referral_code_used", None)  # not a column; only used by the chat signup flow
    data["clinic_id"] = current_user.clinic_id or data.get("clinic_id")
    patient = PatientLead(**data)
    if patient.consent_given:
        patient.consent_timestamp = datetime.utcnow()
    db.add(patient)
    log_action(db, current_user.id, "create_patient", f"Tạo hồ sơ khách: {patient.full_name}")
    db.commit()
    db.refresh(patient)
    return patient


@router.get("/patients/{patient_id}", response_model=PatientDetailOut)
def get_patient_detail(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    patient = db.query(PatientLead).filter(PatientLead.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách hàng")
    _check_same_clinic(patient.clinic_id, current_user)

    appointments = db.query(Appointment).filter(
        Appointment.patient_id == patient.id
    ).order_by(Appointment.start_time.desc()).all()
    conv_count = db.query(Conversation).filter(Conversation.patient_id == patient.id).count()

    detail = PatientDetailOut.model_validate(patient, from_attributes=True)
    detail.appointments = [AppointmentOut.model_validate(a, from_attributes=True) for a in appointments]
    detail.conversation_count = conv_count
    return detail


@router.put("/patients/{patient_id}", response_model=PatientLeadOut)
def update_patient(
    patient_id: int,
    lead_in: PatientLeadUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    patient = db.query(PatientLead).filter(PatientLead.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách hàng")
    _check_same_clinic(patient.clinic_id, current_user)

    for key, value in lead_in.model_dump(exclude_unset=True).items():
        setattr(patient, key, value)

    log_action(db, current_user.id, "update_patient", f"Cập nhật hồ sơ khách #{patient.id}")
    db.commit()
    db.refresh(patient)
    return patient


@router.get("/available-slots")
def get_doctor_available_slots(
    doctor_id: int,
    target_date: date,
    service_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    """
    Get free time slots of a doctor on a date, based on working schedules and booked appointments.
    """
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Không tìm thấy dịch vụ")

    slots = get_available_slots(db, doctor_id, target_date, service.duration_minutes)
    return {
        "doctor_id": doctor_id,
        "date": target_date.isoformat(),
        "duration_minutes": service.duration_minutes,
        "slots": [slot.strftime("%H:%M") for slot in slots]
    }


# --- APPOINTMENTS ---
@router.get("", response_model=List[AppointmentOut])
def get_appointments(
    db: Session = Depends(get_db),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    status: Optional[str] = None,
    doctor_id: Optional[int] = None,
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    query = _scoped(db.query(Appointment), Appointment, current_user)

    if start_date:
        query = query.filter(Appointment.start_time >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        query = query.filter(Appointment.start_time <= datetime.combine(end_date, datetime.max.time()))
    if status:
        query = query.filter(Appointment.status == status)
    if doctor_id:
        query = query.filter(Appointment.doctor_id == doctor_id)

    return query.order_by(Appointment.start_time.asc()).all()


@router.post("", response_model=AppointmentOut)
def create_appointment(
    appt_in: AppointmentCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    # Validate entities exist
    patient = db.query(PatientLead).filter(PatientLead.id == appt_in.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách hàng")
    _check_same_clinic(patient.clinic_id, current_user)

    service = db.query(Service).filter(Service.id == appt_in.service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Không tìm thấy dịch vụ")

    doc = db.query(Doctor).filter(Doctor.id == appt_in.doctor_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Không tìm thấy bác sĩ")

    branch = db.query(Branch).filter(Branch.id == appt_in.branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Không tìm thấy chi nhánh")

    appt = Appointment(**appt_in.model_dump(), clinic_id=current_user.clinic_id or patient.clinic_id,
                       booking_source="staff")
    db.add(appt)
    db.flush()
    emit_event(db, appt.clinic_id, "appointment_created", patient_id=patient.id,
               payload={"appointment_id": appt.id, "service_id": service.id,
                        "service_name": service.name, "source": "staff"})
    log_action(db, current_user.id, "create_appointment",
               f"Tạo lịch hẹn cho {patient.full_name} - {service.name} lúc {appt_in.start_time}")
    db.commit()
    db.refresh(appt)

    # Send email confirmation in background if patient has email
    if patient.email:
        time_str = appt.start_time.strftime("%d/%m/%Y lúc %H:%M")
        html = f"""
        <h3>Xác nhận lịch hẹn khám tại CareDesk AI</h3>
        <p>Xin chào <b>{patient.full_name}</b>,</p>
        <p>Lịch hẹn của bạn đã được tiếp nhận và đang ở trạng thái <b>{appt.status.upper()}</b>.</p>
        <ul>
            <li><b>Dịch vụ:</b> {service.name}</li>
            <li><b>Bác sĩ:</b> {doc.name}</li>
            <li><b>Chi nhánh:</b> {branch.name} ({branch.address})</li>
            <li><b>Thời gian:</b> {time_str}</li>
        </ul>
        <p>Cảm ơn bạn đã lựa chọn CareDesk AI!</p>
        """
        background_tasks.add_task(
            send_email_notification,
            patient.email,
            "CareDesk AI - Xác nhận lịch hẹn khám",
            html
        )

    return appt


@router.put("/{appt_id}", response_model=AppointmentOut)
def update_appointment(
    appt_id: int,
    appt_in: AppointmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Không tìm thấy lịch hẹn")
    _check_same_clinic(appt.clinic_id, current_user)

    old_status = appt.status
    data = appt_in.model_dump()
    data.pop("clinic_id", None)
    for key, value in data.items():
        setattr(appt, key, value)

    handle_status_transition(db, appt, old_status)

    detail = f"Cập nhật lịch hẹn #{appt.id}"
    if old_status != appt.status:
        detail += f" (trạng thái: {old_status} -> {appt.status})"
    log_action(db, current_user.id, "update_appointment", detail)
    db.commit()
    db.refresh(appt)
    return appt


@router.post("/{appt_id}/remind")
async def send_appointment_reminder(
    appt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    """
    Manually trigger a reminder (email + ZNS/SMS) for a specific appointment.

    Sends inline rather than in a background task: a receptionist who clicks
    "nhắc lịch" needs to be told whether it actually went out, and a background
    task cannot report that back.
    """
    from backend.app.services.reminder import build_reminder_text
    from backend.app.services.channel_gateway import send_zns_or_sms
    from backend.app.models.models import ReminderLog

    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Không tìm thấy lịch hẹn")
    _check_same_clinic(appt.clinic_id, current_user)

    patient = appt.patient
    if not patient or (not patient.email and not patient.phone):
        raise HTTPException(status_code=400, detail="Khách hàng không có email hoặc SĐT để nhận nhắc lịch.")

    sent_channels = []
    failures = []
    text = build_reminder_text(appt, "manual")

    if patient.phone:
        result = send_zns_or_sms(db, appt.clinic_id, patient.phone, text)
        if result.delivered:
            db.add(ReminderLog(appointment_id=appt.id, kind="manual", channel=result.channel))
            sent_channels.append(result.channel.upper())
        else:
            failures.append(result.detail or "không gửi được tin tới số điện thoại")

    if patient.email:
        time_str = appt.start_time.strftime("%d/%m/%Y lúc %H:%M")
        html = f"""
        <h3>Nhắc lịch hẹn khám tại CareDesk AI</h3>
        <p>Xin chào <b>{patient.full_name}</b>,</p>
        <p>Đây là tin nhắn nhắc nhở bạn có lịch hẹn sắp tới tại phòng khám của chúng tôi:</p>
        <ul>
            <li><b>Dịch vụ:</b> {appt.service.name}</li>
            <li><b>Bác sĩ:</b> {appt.doctor.name}</li>
            <li><b>Chi nhánh:</b> {appt.branch.name}</li>
            <li><b>Thời gian:</b> {time_str}</li>
        </ul>
        <p>Địa chỉ: {appt.branch.address}</p>
        <p>Vui lòng đến trước 10 phút để chuẩn bị. Trân trọng cảm ơn!</p>
        """
        if await send_email_notification(
            patient.email, "CareDesk AI - Nhắc lịch hẹn khám", html
        ):
            db.add(ReminderLog(appointment_id=appt.id, kind="manual", channel="email"))
            sent_channels.append("EMAIL")
        else:
            failures.append("email chưa cấu hình hoặc gửi lỗi")

    log_action(db, current_user.id, "send_reminder", f"Nhắc lịch thủ công cho lịch hẹn #{appt.id}")
    db.commit()

    if not sent_channels:
        # 502, not 200: nothing reached the patient. Reporting success here is
        # how staff end up believing a patient was reminded when they were not.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Chưa gửi được nhắc lịch. " + "; ".join(failures) +
                   ". Vào Cài đặt để kết nối Zalo ZNS hoặc SMS.",
        )
    msg = f"Đã gửi nhắc lịch qua: {', '.join(sent_channels)}"
    if failures:
        msg += f" (chưa gửi được: {'; '.join(failures)})"
    return {"status": "success", "message": msg}


@router.delete("/{appt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_appointment(
    appt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner)
):
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Không tìm thấy lịch hẹn")
    _check_same_clinic(appt.clinic_id, current_user)
    log_action(db, current_user.id, "delete_appointment", f"Xóa lịch hẹn #{appt.id}")
    db.delete(appt)
    db.commit()
    return
