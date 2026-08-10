"""
Prepaid service packages (gói liệu trình): the clinic's cash-flow machine.
Selling a package books revenue immediately; completed visits burn sessions
automatically (see appointment.handle_status_transition).
"""
from typing import Any, List
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend.app.core.database import get_db
from backend.app.api.deps import verify_receptionist_or_above, verify_owner
from backend.app.models.models import (
    ServicePackage, PatientPackage, PatientLead, RevenueRecord, User
)
from backend.app.schemas.schemas import ServicePackageCreate, ServicePackageOut, SellPackageIn
from backend.app.services.audit import log_action
from backend.app.services.events import emit_event

router = APIRouter()


@router.get("", response_model=List[ServicePackageOut])
def list_packages(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    query = db.query(ServicePackage)
    if current_user.clinic_id:
        query = query.filter(ServicePackage.clinic_id == current_user.clinic_id)
    return query.all()


@router.post("", response_model=ServicePackageOut)
def create_package(
    pkg_in: ServicePackageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner)
) -> Any:
    if not current_user.clinic_id:
        raise HTTPException(status_code=400, detail="Tài khoản chưa gắn với phòng khám.")
    pkg = ServicePackage(**pkg_in.model_dump(), clinic_id=current_user.clinic_id)
    db.add(pkg)
    log_action(db, current_user.id, "create_package", f"Tạo gói: {pkg.name} ({pkg.total_sessions} buổi, {pkg.price:,.0f}đ)")
    db.commit()
    db.refresh(pkg)
    return pkg


@router.put("/{package_id}", response_model=ServicePackageOut)
def update_package(
    package_id: int,
    pkg_in: ServicePackageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner)
) -> Any:
    pkg = db.query(ServicePackage).filter(ServicePackage.id == package_id).first()
    if not pkg:
        raise HTTPException(status_code=404, detail="Không tìm thấy gói")
    if current_user.clinic_id and pkg.clinic_id != current_user.clinic_id:
        raise HTTPException(status_code=403, detail="Gói không thuộc phòng khám của bạn.")
    for key, value in pkg_in.model_dump().items():
        setattr(pkg, key, value)
    log_action(db, current_user.id, "update_package", f"Cập nhật gói #{pkg.id}")
    db.commit()
    db.refresh(pkg)
    return pkg


@router.delete("/{package_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_package(
    package_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner)
):
    pkg = db.query(ServicePackage).filter(ServicePackage.id == package_id).first()
    if not pkg:
        raise HTTPException(status_code=404, detail="Không tìm thấy gói")
    if current_user.clinic_id and pkg.clinic_id != current_user.clinic_id:
        raise HTTPException(status_code=403, detail="Gói không thuộc phòng khám của bạn.")
    log_action(db, current_user.id, "delete_package", f"Xóa gói: {pkg.name} (#{pkg.id})")
    db.delete(pkg)
    db.commit()
    return


@router.post("/sell")
def sell_package(
    sell_in: SellPackageIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    """Sell a package to a patient: prepaid revenue recognized immediately."""
    pkg = db.query(ServicePackage).filter(ServicePackage.id == sell_in.package_id).first()
    patient = db.query(PatientLead).filter(PatientLead.id == sell_in.patient_id).first()
    if not pkg or not patient:
        raise HTTPException(status_code=404, detail="Không tìm thấy gói hoặc khách hàng")
    if current_user.clinic_id and pkg.clinic_id != current_user.clinic_id:
        raise HTTPException(status_code=403, detail="Gói không thuộc phòng khám của bạn.")

    pp = PatientPackage(
        clinic_id=pkg.clinic_id,
        patient_id=patient.id,
        package_id=pkg.id,
        sessions_total=pkg.total_sessions,
        amount_paid=pkg.price,
        expires_at=datetime.now() + timedelta(days=pkg.validity_days or 180)
    )
    db.add(pp)
    db.flush()
    db.add(RevenueRecord(
        clinic_id=pkg.clinic_id, patient_id=patient.id, patient_package_id=pp.id,
        amount=pkg.price, source="package"
    ))
    emit_event(db, pkg.clinic_id, "package_sold", patient_id=patient.id,
               payload={"package_id": pkg.id, "package_name": pkg.name, "amount": pkg.price})
    log_action(db, current_user.id, "sell_package",
               f"Bán gói {pkg.name} cho {patient.full_name} ({pkg.price:,.0f}đ)")
    db.commit()
    db.refresh(pp)
    return {
        "id": pp.id, "patient_id": patient.id, "package_id": pkg.id,
        "sessions_total": pp.sessions_total, "sessions_used": pp.sessions_used,
        "amount_paid": pp.amount_paid, "expires_at": pp.expires_at, "status": pp.status
    }


@router.get("/patient-packages")
def list_patient_packages(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    query = db.query(PatientPackage)
    if current_user.clinic_id:
        query = query.filter(PatientPackage.clinic_id == current_user.clinic_id)
    rows = query.order_by(PatientPackage.purchased_at.desc()).limit(200).all()
    return [{
        "id": pp.id,
        "patient_name": pp.patient.full_name if pp.patient else "?",
        "patient_phone": pp.patient.phone if pp.patient else "",
        "package_name": pp.package.name if pp.package else "?",
        "sessions_total": pp.sessions_total,
        "sessions_used": pp.sessions_used,
        "amount_paid": pp.amount_paid,
        "status": pp.status,
        "purchased_at": pp.purchased_at,
        "expires_at": pp.expires_at,
    } for pp in rows]


@router.post("/patient-packages/{pp_id}/use-session")
def use_session_manually(
    pp_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    """Manually burn one session (walk-in visit without a booked appointment)."""
    pp = db.query(PatientPackage).filter(PatientPackage.id == pp_id).first()
    if not pp:
        raise HTTPException(status_code=404, detail="Không tìm thấy gói của khách")
    if current_user.clinic_id and pp.clinic_id != current_user.clinic_id:
        raise HTTPException(status_code=403, detail="Không thuộc phòng khám của bạn.")
    if pp.status != "active" or pp.sessions_used >= pp.sessions_total:
        raise HTTPException(status_code=400, detail="Gói đã dùng hết hoặc không còn hiệu lực.")

    pp.sessions_used += 1
    if pp.sessions_used >= pp.sessions_total:
        pp.status = "used_up"
        emit_event(db, pp.clinic_id, "package_used_up", patient_id=pp.patient_id,
                   payload={"service_name": pp.package.name if pp.package else "gói liệu trình"})
    log_action(db, current_user.id, "use_package_session", f"Trừ 1 buổi gói #{pp.id} ({pp.sessions_used}/{pp.sessions_total})")
    db.commit()
    return {"id": pp.id, "sessions_used": pp.sessions_used, "sessions_total": pp.sessions_total, "status": pp.status}
