from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend.app.core.database import get_db
from backend.app.api.deps import (
    verify_receptionist_or_above, verify_owner_or_admin, get_current_active_user
)
from backend.app.models.models import Clinic, Branch, Service, Doctor, WorkingSchedule, User
from backend.app.schemas.schemas import (
    ClinicOut, ClinicCreate, BranchOut, BranchCreate,
    ServiceOut, ServiceCreate, DoctorOut, DoctorBase,
    WorkingScheduleOut, WorkingScheduleCreate
)

router = APIRouter()

# --- CLINIC ---
@router.get("", response_model=List[ClinicOut])
def get_clinics(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    return db.query(Clinic).all()

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
    
    for key, value in clinic_in.model_dump().items():
        setattr(clinic, key, value)
    
    db.commit()
    db.refresh(clinic)
    return clinic


# --- BRANCHES ---
@router.get("/branches", response_model=List[BranchOut])
def get_branches(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    return db.query(Branch).all()

@router.post("/branches", response_model=BranchOut)
def create_branch(
    branch_in: BranchCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
) -> Any:
    db_branch = Branch(**branch_in.model_dump())
    db.add(db_branch)
    db.commit()
    db.refresh(db_branch)
    return db_branch

@router.delete("/branches/{branch_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_branch(
    branch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
):
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Không tìm thấy chi nhánh")
    db.delete(branch)
    db.commit()
    return


# --- SERVICES ---
@router.get("/services", response_model=List[ServiceOut])
def get_services(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    return db.query(Service).all()

@router.post("/services", response_model=ServiceOut)
def create_service(
    service_in: ServiceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
) -> Any:
    db_service = Service(**service_in.model_dump())
    db.add(db_service)
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
    
    for key, value in service_in.model_dump().items():
        setattr(service, key, value)
    
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
    db.delete(service)
    db.commit()
    return


# --- DOCTORS ---
@router.get("/doctors", response_model=List[DoctorOut])
def get_doctors(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    return db.query(Doctor).all()

@router.post("/doctors", response_model=DoctorOut)
def create_doctor(
    doctor_in: DoctorBase,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
) -> Any:
    db_doctor = Doctor(**doctor_in.model_dump())
    db.add(db_doctor)
    db.commit()
    db.refresh(db_doctor)
    return db_doctor


# --- SCHEDULES ---
@router.get("/schedules", response_model=List[WorkingScheduleOut])
def get_schedules(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    return db.query(WorkingSchedule).all()

@router.post("/schedules", response_model=WorkingScheduleOut)
def create_schedule(
    schedule_in: WorkingScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
) -> Any:
    # Check if doctor exists
    doc = db.query(Doctor).filter(Doctor.id == schedule_in.doctor_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Không tìm thấy bác sĩ")
    # Check if branch exists
    branch = db.query(Branch).filter(Branch.id == schedule_in.branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Không tìm thấy chi nhánh")
        
    db_sched = WorkingSchedule(**schedule_in.model_dump())
    db.add(db_sched)
    db.commit()
    db.refresh(db_sched)
    return db_sched
