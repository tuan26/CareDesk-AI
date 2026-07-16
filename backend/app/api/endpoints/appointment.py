from typing import Any, List, Optional
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from backend.app.core.database import get_db
from backend.app.core.config import settings
from backend.app.api.deps import verify_receptionist_or_above, verify_owner_or_admin
from backend.app.models.models import Appointment, PatientLead, Service, Doctor, Branch, User
from backend.app.schemas.schemas import AppointmentOut, AppointmentCreate

router = APIRouter()

async def send_email_notification(to_email: str, subject: str, html_content: str):
    """
    Sends an async email using configuration from settings.
    Falls back to print log if credentials are not configured.
    """
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        print(f"[MOCK EMAIL] Gửi tới {to_email}")
        print(f"[MOCK EMAIL] Chủ đề: {subject}")
        print(f"[MOCK EMAIL] Nội dung: {html_content[:200]}...")
        return

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
        print(f"[EMAIL] Đã gửi thư thành công tới {to_email}")
    except Exception as e:
        print(f"[EMAIL ERROR] Không thể gửi email tới {to_email}: {e}")


@router.get("", response_model=List[AppointmentOut])
def get_appointments(
    db: Session = Depends(get_db),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    status: Optional[str] = None,
    doctor_id: Optional[int] = None,
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    query = db.query(Appointment)
    
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
        
    service = db.query(Service).filter(Service.id == appt_in.service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Không tìm thấy dịch vụ")
        
    doc = db.query(Doctor).filter(Doctor.id == appt_in.doctor_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Không tìm thấy bác sĩ")
        
    branch = db.query(Branch).filter(Branch.id == appt_in.branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Không tìm thấy chi nhánh")
        
    appt = Appointment(**appt_in.model_dump())
    db.add(appt)
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
        
    for key, value in appt_in.model_dump().items():
        setattr(appt, key, value)
        
    db.commit()
    db.refresh(appt)
    return appt


@router.post("/{appt_id}/remind")
def send_appointment_reminder(
    appt_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    """
    Manually trigger an email reminder for a specific appointment.
    """
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Không tìm thấy lịch hẹn")
        
    patient = appt.patient
    if not patient or not patient.email:
        raise HTTPException(status_code=400, detail="Khách hàng không có địa chỉ email để nhận nhắc lịch.")
        
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
    background_tasks.add_task(
        send_email_notification,
        patient.email,
        "CareDesk AI - Nhắc lịch hẹn khám",
        html
    )
    
    return {"status": "success", "message": f"Đã lên lịch gửi email nhắc lịch cho {patient.email}"}


@router.delete("/{appt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_appointment(
    appt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
):
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Không tìm thấy lịch hẹn")
    db.delete(appt)
    db.commit()
    return
