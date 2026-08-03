"""Staff workflow for administrative booking requests from the V1 public widget."""
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api.deps import verify_receptionist_or_above
from backend.app.core.database import get_db
from backend.app.models.models import Appointment, BookingRequest, Branch, Doctor, Service, User
from backend.app.schemas.schemas import AppointmentCreate, AppointmentOut, BookingRequestOut, BookingRequestStatusUpdate
from backend.app.services.ai_engine import get_available_slots
from backend.app.services.audit import log_action
from backend.app.services.events import emit_event

router = APIRouter()


def _scoped(query, user: User):
    return query.filter(BookingRequest.clinic_id == user.clinic_id) if user.clinic_id else query


@router.get("", response_model=List[BookingRequestOut])
def list_booking_requests(
    request_status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above),
) -> Any:
    query = _scoped(db.query(BookingRequest), current_user)
    if request_status:
        query = query.filter(BookingRequest.status == request_status)
    return query.order_by(BookingRequest.created_at.desc()).all()


@router.post("/{request_id}/convert", response_model=AppointmentOut)
def convert_booking_request(
    request_id: int,
    appointment_in: AppointmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above),
) -> Any:
    """Create an Appointment only after staff confirms a BookingRequest.

    Public chat can create only a request. This endpoint is deliberately staff
    authenticated and marks the request converted in the same transaction.
    """
    request = _scoped(db.query(BookingRequest), current_user).filter(BookingRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy yêu cầu đặt lịch.")
    if request.status in {"converted", "cancelled"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Yêu cầu này không thể chuyển thành lịch hẹn.")
    if request.patient_id != appointment_in.patient_id or request.service_id != appointment_in.service_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Lịch hẹn phải dùng khách hàng và dịch vụ của yêu cầu đặt lịch.")

    service = db.query(Service).filter(Service.id == appointment_in.service_id, Service.clinic_id == request.clinic_id).first()
    doctor = db.query(Doctor).filter(Doctor.id == appointment_in.doctor_id, Doctor.clinic_id == request.clinic_id).first()
    branch = db.query(Branch).filter(Branch.id == appointment_in.branch_id, Branch.clinic_id == request.clinic_id).first()
    if not service or not doctor or not branch:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Bác sĩ, chi nhánh hoặc dịch vụ không thuộc phòng khám này.")
    if appointment_in.end_time <= appointment_in.start_time:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Thời gian kết thúc phải sau thời gian bắt đầu.")

    requested_slot = appointment_in.start_time.replace(tzinfo=None).time()
    available_slots = get_available_slots(
        db, doctor.id, appointment_in.start_time.date(), service.duration_minutes
    )
    if requested_slot not in available_slots:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Khung giờ này không còn trống. Vui lòng chọn khung giờ khác.")

    appointment = Appointment(
        **appointment_in.model_dump(), clinic_id=request.clinic_id,
        conversation_id=request.conversation_id, booking_source="ai_chat",
    )
    db.add(appointment)
    db.flush()
    request.status = "converted"
    emit_event(db, request.clinic_id, "appointment_created", patient_id=request.patient_id,
               payload={"appointment_id": appointment.id, "booking_request_id": request.id,
                        "service_id": service.id, "service_name": service.name, "source": "ai_chat"})
    log_action(db, current_user.id, "convert_booking_request",
               f"Booking request #{request.id} -> appointment #{appointment.id}")
    db.commit()
    db.refresh(appointment)
    return appointment


@router.patch("/{request_id}", response_model=BookingRequestOut)
def update_booking_request_status(
    request_id: int,
    body: BookingRequestStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above),
) -> Any:
    request = _scoped(db.query(BookingRequest), current_user).filter(BookingRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy yêu cầu đặt lịch.")
    request.status = body.status
    log_action(db, current_user.id, "update_booking_request", f"Booking request #{request.id} -> {request.status}")
    db.commit()
    db.refresh(request)
    return request
