from pydantic import BaseModel, EmailStr
from datetime import datetime, time
from typing import Optional, List, Dict, Any

# User & Auth
class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    role: str = "receptionist"

class UserCreate(UserBase):
    password: str

class UserOut(UserBase):
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = None


# Clinic & Branch
class ClinicBase(BaseModel):
    name: str
    logo_url: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    cancellation_policy: Optional[str] = None

class ClinicCreate(ClinicBase):
    pass

class ClinicOut(ClinicBase):
    id: int

    class Config:
        from_attributes = True

class BranchBase(BaseModel):
    name: str
    address: str
    phone: Optional[str] = None
    working_hours: Optional[str] = None

class BranchCreate(BranchBase):
    clinic_id: int

class BranchOut(BranchBase):
    id: int
    clinic_id: int

    class Config:
        from_attributes = True


# Service
class ServiceBase(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
    duration_minutes: int
    preparation_instructions: Optional[str] = None
    faq_data: Optional[List[Dict[str, str]]] = None

class ServiceCreate(ServiceBase):
    clinic_id: int

class ServiceOut(ServiceBase):
    id: int
    clinic_id: int

    class Config:
        from_attributes = True


# Doctor
class DoctorBase(BaseModel):
    name: str
    specialty: Optional[str] = None
    branch_id: Optional[int] = None
    is_active: bool = True

class DoctorCreate(DoctorBase):
    pass

class DoctorOut(DoctorBase):
    id: int

    class Config:
        from_attributes = True


# Working Schedule
class WorkingScheduleBase(BaseModel):
    doctor_id: int
    branch_id: int
    day_of_week: int  # 0-6
    start_time: time
    end_time: time

class WorkingScheduleCreate(WorkingScheduleBase):
    pass

class WorkingScheduleOut(WorkingScheduleBase):
    id: int

    class Config:
        from_attributes = True


# Patient Lead & Consent
class PatientLeadBase(BaseModel):
    full_name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    source: str = "web"
    consent_given: bool = False

class PatientLeadCreate(PatientLeadBase):
    pass

class PatientLeadOut(PatientLeadBase):
    id: int
    consent_timestamp: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


# Message & Conversation
class MessageBase(BaseModel):
    content: str

class MessageCreate(MessageBase):
    sender: str  # patient | bot | agent

class MessageOut(BaseModel):
    id: int
    conversation_id: int
    sender: str
    content: str
    created_at: datetime
    evaluation_metadata: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True

class ConversationOut(BaseModel):
    id: int
    patient_id: int
    channel: str
    status: str
    created_at: datetime
    updated_at: datetime
    patient: Optional[PatientLeadOut] = None
    messages: List[MessageOut] = []

    class Config:
        from_attributes = True

class ConversationStatusUpdate(BaseModel):
    status: str  # bot_active | handoff_requested | agent_active


# Appointment
class AppointmentBase(BaseModel):
    patient_id: int
    service_id: int
    doctor_id: int
    branch_id: int
    start_time: datetime
    end_time: datetime
    status: str = "pending"  # pending | confirmed | cancelled | completed | no_show
    note: Optional[str] = None

class AppointmentCreate(AppointmentBase):
    pass

class AppointmentOut(AppointmentBase):
    id: int
    created_at: datetime
    patient: Optional[PatientLeadOut] = None
    service: Optional[ServiceOut] = None
    doctor: Optional[DoctorOut] = None
    branch: Optional[BranchOut] = None

    class Config:
        from_attributes = True


# AI Safety Rule
class AISafetyRuleBase(BaseModel):
    category: str
    keyword_pattern: str
    fallback_message: str
    force_handoff: bool = True

class AISafetyRuleCreate(AISafetyRuleBase):
    pass

class AISafetyRuleOut(AISafetyRuleBase):
    id: int

    class Config:
        from_attributes = True


# Audit Log
class AuditLogOut(BaseModel):
    id: int
    user_id: Optional[int] = None
    action: str
    details: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
