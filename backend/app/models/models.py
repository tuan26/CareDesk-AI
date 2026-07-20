from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Time, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.app.core.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=True, index=True)
    # Chain owner accounts belong to an organization instead of a single clinic.
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String, default="receptionist")  # admin | owner | receptionist | org_owner
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True)  # link account -> doctor (copilot personalization)
    is_platform_admin = Column(Boolean, default=False)  # vendor/publisher super-admin (cross-tenant)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    audit_logs = relationship("AuditLog", back_populates="user")


class Organization(Base):
    """A chain / group that owns multiple clinics. Enables cross-clinic roll-up."""
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=True)  # public link /g/<slug>
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    clinics = relationship("Clinic", back_populates="organization")


class Plan(Base):
    """Subscription plan catalogue managed by the platform admin (name/quota/price/trial)."""
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True, nullable=False)  # free | pro | vip ...
    name = Column(String, nullable=False)
    monthly_quota = Column(Integer, default=200)  # AI conversations (bot replies) per month
    price = Column(Float, default=0.0)  # đồng / month
    trial_days = Column(Integer, default=0)  # free trial length; 0 = none
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Clinic(Base):
    __tablename__ = "clinics"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)
    slug = Column(String, unique=True, index=True, nullable=True)  # public link /c/<slug>
    name = Column(String, nullable=False)
    logo_url = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    address = Column(String, nullable=True)
    cancellation_policy = Column(Text, nullable=True)
    plan = Column(String, default="free")  # denormalised plan code (free | pro ...)
    plan_id = Column(Integer, ForeignKey("plans.id", ondelete="SET NULL"), nullable=True)
    trial_ends_at = Column(DateTime(timezone=True), nullable=True)  # set while on a free trial
    ai_quota_monthly = Column(Integer, default=200)  # max bot replies per month
    monthly_fee = Column(Float, default=0.0)  # subscription fee, used for ROI math
    deposit_amount = Column(Float, default=0.0)  # 0 = deposits disabled
    google_review_url = Column(String, nullable=True)  # link sent to happy patients
    digest_enabled = Column(Boolean, default=True)  # daily owner digest
    is_active = Column(Boolean, default=True)  # suspended clinics: AI + logins blocked
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    organization = relationship("Organization", back_populates="clinics")
    plan_ref = relationship("Plan")
    branches = relationship("Branch", back_populates="clinic", cascade="all, delete-orphan")
    services = relationship("Service", back_populates="clinic", cascade="all, delete-orphan")


class Branch(Base):
    __tablename__ = "branches"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    address = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    working_hours = Column(String, nullable=True)  # e.g., "08:00 - 20:00"

    clinic = relationship("Clinic", back_populates="branches")
    schedules = relationship("WorkingSchedule", back_populates="branch", cascade="all, delete-orphan")
    appointments = relationship("Appointment", back_populates="branch")


class Service(Base):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False, default=0.0)
    duration_minutes = Column(Integer, nullable=False, default=30)
    preparation_instructions = Column(Text, nullable=True)
    faq_data = Column(JSON, nullable=True)  # List of Q&A dictionaries for RAG fallback

    clinic = relationship("Clinic", back_populates="services")
    appointments = relationship("Appointment", back_populates="service")


class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=True, index=True)
    name = Column(String, nullable=False)
    specialty = Column(String, nullable=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, default=True)

    schedules = relationship("WorkingSchedule", back_populates="doctor", cascade="all, delete-orphan")
    appointments = relationship("Appointment", back_populates="doctor")


class WorkingSchedule(Base):
    __tablename__ = "working_schedules"

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    day_of_week = Column(Integer, nullable=False)  # 0 = Monday, 6 = Sunday
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)

    doctor = relationship("Doctor", back_populates="schedules")
    branch = relationship("Branch", back_populates="schedules")


class PatientLead(Base):
    __tablename__ = "patient_leads"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=True, index=True)
    full_name = Column(String, nullable=False)
    phone = Column(String, index=True, nullable=True)
    email = Column(String, nullable=True)
    source = Column(String, default="web")  # web | zalo | facebook
    external_id = Column(String, index=True, nullable=True)  # user id on Zalo/Facebook
    consent_given = Column(Boolean, default=False)
    consent_timestamp = Column(DateTime(timezone=True), nullable=True)
    note = Column(Text, nullable=True)  # CRM note by staff
    tags = Column(JSON, nullable=True)  # e.g. ["VIP", "Liệu trình mụn"]
    referral_code = Column(String, index=True, nullable=True)  # this patient's own code to share
    referred_by_patient_id = Column(Integer, ForeignKey("patient_leads.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    appointments = relationship("Appointment", back_populates="patient")
    conversations = relationship("Conversation", back_populates="patient", cascade="all, delete-orphan")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=True, index=True)
    patient_id = Column(Integer, ForeignKey("patient_leads.id", ondelete="CASCADE"), nullable=False)
    channel = Column(String, default="web")  # web | zalo | facebook
    status = Column(String, default="bot_active")  # bot_active | handoff_requested | agent_active
    booking_state = Column(JSON, nullable=True)  # AI booking flow state machine
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    patient = relationship("PatientLead", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    sender = Column(String, nullable=False)  # patient | bot | agent
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    evaluation_metadata = Column(JSON, nullable=True)  # metadata for testing/evaluating quality

    conversation = relationship("Conversation", back_populates="messages")


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=True, index=True)
    patient_id = Column(Integer, ForeignKey("patient_leads.id", ondelete="CASCADE"), nullable=False)
    service_id = Column(Integer, ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    status = Column(String, default="pending")  # pending | awaiting_deposit | confirmed | cancelled | completed | no_show
    note = Column(Text, nullable=True)
    booking_source = Column(String, default="staff")  # staff | ai_chat | ai_followup | campaign | referral
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    patient = relationship("PatientLead", back_populates="appointments")
    service = relationship("Service", back_populates="appointments")
    doctor = relationship("Doctor", back_populates="appointments")
    branch = relationship("Branch", back_populates="appointments")


class AISafetyRule(Base):
    __tablename__ = "ai_safety_rules"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=True, index=True)  # NULL = global rule for all clinics
    category = Column(String, nullable=False)  # urgent | clinical_diagnosis | pediatric | pregnancy | medication
    keyword_pattern = Column(String, nullable=False)  # comma separated or regex keywords
    fallback_message = Column(Text, nullable=False)
    force_handoff = Column(Boolean, default=True)


class ChannelIntegration(Base):
    __tablename__ = "channel_integrations"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(String, nullable=False)  # zalo | facebook
    enabled = Column(Boolean, default=False)
    access_token = Column(String, nullable=True)  # Zalo OA access token / FB Page access token
    verify_token = Column(String, nullable=True)  # webhook verification token
    extra_config = Column(JSON, nullable=True)  # e.g. {"zns_template_id": "..."}
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ReminderLog(Base):
    __tablename__ = "reminder_logs"

    id = Column(Integer, primary_key=True, index=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String, nullable=False)  # 24h | 2h | manual
    channel = Column(String, nullable=False)  # email | zns | sms
    sent_at = Column(DateTime(timezone=True), server_default=func.now())


# ============ REVENUE ENGINE ============

class DomainEvent(Base):
    """Append-only event log: every business fact feeds the automation engine."""
    __tablename__ = "domain_events"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=True, index=True)
    event_type = Column(String, nullable=False, index=True)  # price_asked | appointment_created | appointment_completed | appointment_cancelled | package_used_up | deposit_paid ...
    patient_id = Column(Integer, ForeignKey("patient_leads.id", ondelete="CASCADE"), nullable=True, index=True)
    payload = Column(JSON, nullable=True)
    processed = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AutomationRule(Base):
    """Trigger -> delay -> action. New revenue features become rows, not code."""
    __tablename__ = "automation_rules"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    trigger_type = Column(String, default="event")  # event | recurring
    trigger_event = Column(String, nullable=True)  # for event rules
    delay_minutes = Column(Integer, default=0)
    condition = Column(JSON, nullable=True)  # {"service_id": 1} | {"inactive_days": 180} ...
    action_type = Column(String, default="send_message")  # send_message | review_request | notify_waitlist
    message_template = Column(Text, nullable=True)  # {name} {service} {clinic} placeholders
    cancel_on_events = Column(JSON, nullable=True)  # e.g. ["appointment_created"]
    enabled = Column(Boolean, default=True)
    is_system = Column(Boolean, default=False)  # seeded defaults
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ScheduledAction(Base):
    __tablename__ = "scheduled_actions"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=True, index=True)
    rule_id = Column(Integer, ForeignKey("automation_rules.id", ondelete="CASCADE"), nullable=True)
    patient_id = Column(Integer, ForeignKey("patient_leads.id", ondelete="CASCADE"), nullable=True, index=True)
    due_at = Column(DateTime(timezone=True), nullable=False, index=True)
    status = Column(String, default="pending", index=True)  # pending | sent | cancelled | failed
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    executed_at = Column(DateTime(timezone=True), nullable=True)


class RevenueRecord(Base):
    """Revenue ledger with attribution: the number behind 'AI made you X dong'."""
    __tablename__ = "revenue_records"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=True, index=True)
    patient_id = Column(Integer, ForeignKey("patient_leads.id", ondelete="SET NULL"), nullable=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True)
    patient_package_id = Column(Integer, ForeignKey("patient_packages.id", ondelete="SET NULL"), nullable=True)
    amount = Column(Float, nullable=False, default=0.0)
    source = Column(String, default="staff")  # staff | ai_chat | ai_followup | campaign | referral | package
    recorded_at = Column(DateTime(timezone=True), server_default=func.now())


class ServicePackage(Base):
    """Prepaid multi-session package (5 buổi laser...) sold by the clinic."""
    __tablename__ = "service_packages"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True)
    service_id = Column(Integer, ForeignKey("services.id", ondelete="CASCADE"), nullable=True)
    name = Column(String, nullable=False)
    total_sessions = Column(Integer, nullable=False, default=5)
    price = Column(Float, nullable=False, default=0.0)
    validity_days = Column(Integer, default=180)
    active = Column(Boolean, default=True)

    service = relationship("Service")


class PatientPackage(Base):
    __tablename__ = "patient_packages"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=True, index=True)
    patient_id = Column(Integer, ForeignKey("patient_leads.id", ondelete="CASCADE"), nullable=False, index=True)
    package_id = Column(Integer, ForeignKey("service_packages.id", ondelete="CASCADE"), nullable=False)
    sessions_total = Column(Integer, nullable=False)
    sessions_used = Column(Integer, default=0)
    amount_paid = Column(Float, default=0.0)
    status = Column(String, default="active")  # active | used_up | expired
    purchased_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)

    package = relationship("ServicePackage")
    patient = relationship("PatientLead")


class Payment(Base):
    """Deposit / package payments. Mock gateway by default, VNPay/MoMo adapter-ready."""
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=True, index=True)
    patient_id = Column(Integer, ForeignKey("patient_leads.id", ondelete="SET NULL"), nullable=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id", ondelete="CASCADE"), nullable=True)
    amount = Column(Float, nullable=False)
    purpose = Column(String, default="deposit")  # deposit | package
    method = Column(String, default="mock_qr")  # mock_qr | vnpay | momo
    status = Column(String, default="pending", index=True)  # pending | paid | refunded | cancelled
    provider_ref = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    paid_at = Column(DateTime(timezone=True), nullable=True)


class WaitlistEntry(Base):
    """Patients waiting for a slot; auto-notified when a matching slot frees up."""
    __tablename__ = "waitlist_entries"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=True, index=True)
    patient_id = Column(Integer, ForeignKey("patient_leads.id", ondelete="CASCADE"), nullable=False)
    service_id = Column(Integer, ForeignKey("services.id", ondelete="CASCADE"), nullable=True)
    preferred_date = Column(String, nullable=True)  # ISO date or NULL = any
    status = Column(String, default="waiting", index=True)  # waiting | notified | fulfilled | cancelled
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    notified_at = Column(DateTime(timezone=True), nullable=True)

    patient = relationship("PatientLead")
    service = relationship("Service")


class ReviewRequest(Base):
    """Post-visit rating ask. Low ratings are intercepted before they hit Google."""
    __tablename__ = "review_requests"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=True, index=True)
    patient_id = Column(Integer, ForeignKey("patient_leads.id", ondelete="CASCADE"), nullable=False, index=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id", ondelete="CASCADE"), nullable=True)
    status = Column(String, default="pending", index=True)  # pending | answered | escalated
    rating = Column(Integer, nullable=True)  # 1-5
    feedback = Column(Text, nullable=True)
    sent_at = Column(DateTime(timezone=True), server_default=func.now())
    answered_at = Column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String, nullable=False)  # e.g. "create_appointment"
    details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="audit_logs")
