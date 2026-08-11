from pydantic import BaseModel, EmailStr
from datetime import date, datetime, time
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
    clinic_id: Optional[int] = None
    organization_id: Optional[int] = None
    is_platform_admin: bool = False
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ClinicRegister(BaseModel):
    clinic_name: str
    owner_name: str
    email: EmailStr
    password: str
    phone: Optional[str] = None
    address: Optional[str] = None

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
    og_image_url: Optional[str] = None  # social link preview, ~1200x630
    phone: Optional[str] = None
    address: Optional[str] = None
    cancellation_policy: Optional[str] = None
    deposit_amount: Optional[float] = None  # 0 = deposits off
    google_review_url: Optional[str] = None
    digest_enabled: Optional[bool] = None
    default_locale: Optional[str] = "vi"
    public_chat_v1_enabled: Optional[bool] = False

class ClinicCreate(ClinicBase):
    pass

class ClinicOut(ClinicBase):
    id: int
    plan: str = "free"
    ai_quota_monthly: int = 200
    monthly_fee: Optional[float] = 0.0

    class Config:
        from_attributes = True

class BranchBase(BaseModel):
    name: str
    address: str
    phone: Optional[str] = None
    working_hours: Optional[str] = None
    # Directions. map_url is whatever the clinic pastes from Google Maps;
    # lat/lng additionally feed schema.org geo for rich results.
    map_url: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class BranchCreate(BranchBase):
    clinic_id: int

class BranchOut(BranchBase):
    id: int
    clinic_id: int
    slug: Optional[str] = None
    landing_enabled: bool = False
    is_active: bool = True

    class Config:
        from_attributes = True


class BranchUpdate(BaseModel):
    """Partial update. `slug` moves the public URL and is deliberately separate
    from `name` — renaming a branch must never break printed QR codes."""
    name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    working_hours: Optional[str] = None
    map_url: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    landing_enabled: Optional[bool] = None
    is_active: Optional[bool] = None
    slug: Optional[str] = None


# Service
class ServiceBase(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
    duration_minutes: int
    preparation_instructions: Optional[str] = None
    faq_data: Optional[List[Dict[str, str]]] = None
    localized_content: Optional[Dict[str, Dict[str, Any]]] = None

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
    clinic_id: Optional[int] = None
    branch_id: Optional[int] = None  # location the patient came from / picked
    locale: Optional[str] = None
    referral_code_used: Optional[str] = None  # friend's code entered at signup

class PatientLeadOut(PatientLeadBase):
    id: int
    consent_timestamp: Optional[datetime] = None
    note: Optional[str] = None
    tags: Optional[List[str]] = None
    referral_code: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class PatientLeadUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    note: Optional[str] = None
    tags: Optional[List[str]] = None


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
    clinic_id: Optional[int] = None
    patient_id: int
    channel: str
    status: str
    locale: Optional[str] = None
    public_session_token: Optional[str] = None
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
    booking_source: Optional[str] = "staff"
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


# Channel Integration
class ChannelIntegrationIn(BaseModel):
    channel: str  # zalo | facebook
    enabled: bool = False
    access_token: Optional[str] = None
    verify_token: Optional[str] = None
    extra_config: Optional[Dict[str, Any]] = None

class ChannelIntegrationOut(BaseModel):
    id: int
    channel: str
    enabled: bool
    access_token_masked: Optional[str] = None
    verify_token: Optional[str] = None
    extra_config: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


# Patient detail (mini-CRM)
class PatientDetailOut(PatientLeadOut):
    appointments: List["AppointmentOut"] = []
    conversation_count: int = 0


# Service Packages (prepaid multi-session)
class ServicePackageCreate(BaseModel):
    name: str
    service_id: Optional[int] = None
    total_sessions: int = 5
    price: float
    validity_days: int = 180
    active: bool = True

class ServicePackageOut(ServicePackageCreate):
    id: int
    clinic_id: int

    class Config:
        from_attributes = True

class SellPackageIn(BaseModel):
    patient_id: int
    package_id: int


# Automation rules
class AutomationRuleUpdate(BaseModel):
    enabled: Optional[bool] = None
    message_template: Optional[str] = None
    delay_minutes: Optional[int] = None


# Waitlist
class WaitlistCreate(BaseModel):
    patient_id: int
    service_id: Optional[int] = None
    preferred_date: Optional[str] = None


# Copilot
class CopilotAsk(BaseModel):
    question: str


# ===== Subscription plans =====
class PlanBase(BaseModel):
    code: str
    name: str
    monthly_quota: int = 200
    price: float = 0.0
    trial_days: int = 0
    is_active: bool = True

class PlanCreate(PlanBase):
    pass

class PlanUpdate(BaseModel):
    name: Optional[str] = None
    monthly_quota: Optional[int] = None
    price: Optional[float] = None
    trial_days: Optional[int] = None
    is_active: Optional[bool] = None

class PlanOut(PlanBase):
    id: int

    class Config:
        from_attributes = True


# ===== Platform super-admin (vendor) =====
class PlatformClinicCreate(BaseModel):
    clinic_name: str
    owner_name: str
    owner_email: EmailStr
    owner_password: str
    phone: Optional[str] = None
    address: Optional[str] = None
    plan_id: Optional[int] = None       # preferred: pick a plan row
    plan: Optional[str] = None          # fallback: plan code
    monthly_fee: Optional[float] = None  # override plan price if set
    organization_id: Optional[int] = None
    seed_demo_catalogue: bool = True     # create starter branch/services/doctor

class PlatformClinicUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    logo_url: Optional[str] = None
    og_image_url: Optional[str] = None
    slug: Optional[str] = None
    plan_id: Optional[int] = None
    ai_quota_monthly: Optional[int] = None
    monthly_fee: Optional[float] = None
    is_active: Optional[bool] = None
    landing_enabled: Optional[bool] = None
    organization_id: Optional[int] = None
    trial_ends_at: Optional[datetime] = None


# ===== Public (slug resolution for per-clinic links) =====
class PublicBranchOut(BaseModel):
    id: int
    slug: Optional[str] = None
    name: str
    address: Optional[str] = None
    phone: Optional[str] = None
    working_hours: Optional[str] = None
    bookable: bool = True  # False = no working schedule, cannot take a booking


class PublicClinicOut(BaseModel):
    clinic_id: int
    slug: Optional[str] = None
    name: str
    logo_url: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    is_active: bool = True
    default_locale: str = "vi"
    public_chat_v1_enabled: bool = False
    # The location the public URL pointed at, plus every location the patient
    # may pick when the URL named none.
    branch: Optional[PublicBranchOut] = None
    branches: list[PublicBranchOut] = []


# ===== Organization (chain) =====
class OrganizationCreate(BaseModel):
    name: str
    owner_name: str
    owner_email: EmailStr
    owner_password: str

class OrganizationOut(BaseModel):
    id: int
    name: str
    slug: Optional[str] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

class OrganizationUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    is_active: Optional[bool] = None
    landing_enabled: Optional[bool] = None


class AssignClinicToOrg(BaseModel):
    clinic_id: int
    organization_id: Optional[int] = None  # None detaches the clinic from its chain


# ===== V1 booking request inbox =====
class BookingRequestStatusUpdate(BaseModel):
    status: str  # requested | contacted | converted | cancelled


class BookingRequestOut(BaseModel):
    id: int
    clinic_id: int
    conversation_id: Optional[int] = None
    patient_id: Optional[int] = None
    service_id: Optional[int] = None
    locale: str
    service_or_need: str
    preferred_time: Optional[str] = None
    full_name: str
    contact_method: str
    contact_value: str
    note: Optional[str] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


# Doctor time off (leave, public holidays, half days)
class TimeOffBase(BaseModel):
    # None = the whole clinic is closed, e.g. a public holiday.
    doctor_id: Optional[int] = None
    start_date: date
    end_date: date
    # Both None = the whole day; set both for a half day.
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    reason: Optional[str] = None


class TimeOffOut(TimeOffBase):
    id: int
    clinic_id: int
    doctor_name: Optional[str] = None

    class Config:
        from_attributes = True
