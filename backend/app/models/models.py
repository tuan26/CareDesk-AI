from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Time, ForeignKey, Text,
    JSON, UniqueConstraint,
)
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
    # See core/roles.py. Clinic-level: owner | receptionist.
    # Above a clinic (clinic_id is NULL): org_owner | platform.
    role = Column(String, default="receptionist")
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True)  # link account -> doctor (copilot personalization)
    is_platform_admin = Column(Boolean, default=False)  # vendor/publisher super-admin (cross-tenant)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    audit_logs = relationship("AuditLog", back_populates="user")


class SlugRegistry(Base):
    """Global registry of every public URL slug — the single source of truth.

    Why a registry instead of a UNIQUE column per table: organizations, clinics
    and branches all share one public namespace (/book/<slug>). Per-table
    uniqueness lets a clinic and a branch claim the same slug, which would route
    a patient to the wrong clinic — a safety bug, not a cosmetic one. Here the
    primary key enforces global uniqueness at the database level, resolution is
    one indexed lookup instead of N table probes, and adding a new entity type
    later needs no change to the slug logic.

    Rows are never deleted on rename. Setting is_active=False keeps the old slug
    resolvable so printed QR codes and indexed URLs can be 301-redirected to the
    entity's current slug.

    `entity_type='reserved'` rows (entity_id NULL) block system paths like
    'admin' or 'api' from ever being handed to a tenant.
    """
    __tablename__ = "slug_registry"

    slug = Column(String, primary_key=True)
    entity_type = Column(String, nullable=False, index=True)  # organization | clinic | branch | reserved
    entity_id = Column(Integer, nullable=True, index=True)    # NULL for reserved words
    is_active = Column(Boolean, default=True, nullable=False)  # False = superseded, 301 only
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Organization(Base):
    """A chain / group that owns multiple clinics. Enables cross-clinic roll-up."""
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=True)  # public link /g/<slug>
    landing_enabled = Column(Boolean, default=True, nullable=False)  # chain landing page at /book/<slug>
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
    # Social link preview. A logo is the wrong shape for this — crawlers want
    # ~1200x630 and ignore images under 200x200 — so it gets its own field and
    # falls back to logo_url only when unset.
    og_image_url = Column(String, nullable=True)
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
    default_locale = Column(String, default="vi", nullable=False)  # vi | ja | en
    public_chat_v1_enabled = Column(Boolean, default=False, nullable=False)  # opt-in session-bound public chat
    landing_enabled = Column(Boolean, default=True, nullable=False)  # public landing page at /book/<slug>
    is_active = Column(Boolean, default=True)  # suspended clinics: AI + logins blocked

    # --- Onboarding -----------------------------------------------------
    onboarding_completed_at = Column(DateTime(timezone=True), nullable=True)

    # What the clinic was doing BEFORE CareDesk, captured during onboarding.
    # We sell "more bookings, fewer no-shows" — both are comparisons, and without
    # a number the clinic stated themselves on day one there is nothing to
    # compare against when they ask what they got for their money. The figures
    # are their own estimate and will be rough; being their own is the point.
    baseline_monthly_bookings = Column(Integer, nullable=True)
    baseline_no_show_percent = Column(Float, nullable=True)
    baseline_daily_price_asks = Column(Integer, nullable=True)
    baseline_captured_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    organization = relationship("Organization", back_populates="clinics")
    plan_ref = relationship("Plan")
    branches = relationship("Branch", back_populates="clinic", cascade="all, delete-orphan")
    services = relationship("Service", back_populates="clinic", cascade="all, delete-orphan")


class Branch(Base):
    """A physical location of a Clinic. The public-facing "cơ sở" patients pick.

    Billing/tenancy stay at the Clinic level: one clinic pays one subscription
    no matter how many branches it runs, and services/patients/quota are shared
    across them.
    """
    __tablename__ = "branches"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False)
    # Public link /book/<brand>/<slug>. Always generated, even when the branch
    # landing is off, so enabling it later never changes the URL. Never
    # re-derived from `name` - renaming a branch must not break printed QR
    # codes; changing it is an explicit action (see core/slug.py).
    slug = Column(String, unique=True, index=True, nullable=True)
    name = Column(String, nullable=False)
    address = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    working_hours = Column(String, nullable=True)  # e.g., "08:00 - 20:00"
    landing_enabled = Column(Boolean, default=False, nullable=False)  # opt-in per-branch landing page
    is_active = Column(Boolean, default=True, nullable=False)  # closed/renovating: hide without suspending the clinic

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
    faq_data = Column(JSON, nullable=True)  # Legacy list of Q&A dictionaries for RAG fallback
    localized_content = Column(JSON, nullable=True)  # {locale: {name, description, preparation_instructions, faq}}

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
    locale = Column(String, nullable=True)  # Explicit patient locale; NULL uses Clinic.default_locale
    # Which location the patient arrived from (/chat/<brand>/<branch>). Without
    # it the booking flow just took the first doctor with a free slot, so every
    # conversation ended up booking whichever branch that doctor happened to
    # work at, no matter which one the patient clicked.
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="SET NULL"), nullable=True, index=True)
    booking_state = Column(JSON, nullable=True)  # AI booking flow state machine
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    patient = relationship("PatientLead", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")
    public_sessions = relationship("PublicChatSession", back_populates="conversation", cascade="all, delete-orphan")


class PublicChatSession(Base):
    """Revocable, rotating bearer credential for an unauthenticated web conversation."""
    __tablename__ = "public_chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    previous_token_hash = Column(String(64), nullable=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    previous_expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    conversation = relationship("Conversation", back_populates="public_sessions")


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
    # See core/booking_rules.py for which statuses occupy the slot.
    status = Column(String, default="pending")  # pending | awaiting_deposit | confirmed | cancelled | completed | no_show
    # While awaiting a deposit the slot is held. Without a deadline one patient
    # who walks away from the payment page blocks that time forever.
    hold_expires_at = Column(DateTime(timezone=True), nullable=True)
    note = Column(Text, nullable=True)
    booking_source = Column(String, default="staff")  # staff | ai_chat | ai_followup | campaign | referral
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    patient = relationship("PatientLead", back_populates="appointments")
    service = relationship("Service", back_populates="appointments")
    doctor = relationship("Doctor", back_populates="appointments")
    branch = relationship("Branch", back_populates="appointments")


class BookingRequest(Base):
    """Administrative request only; staff/calendar integration creates an Appointment later."""
    __tablename__ = "booking_requests"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    patient_id = Column(Integer, ForeignKey("patient_leads.id", ondelete="SET NULL"), nullable=True, index=True)
    service_id = Column(Integer, ForeignKey("services.id", ondelete="SET NULL"), nullable=True, index=True)
    locale = Column(String, nullable=False, default="vi")
    service_or_need = Column(Text, nullable=False)
    preferred_time = Column(String, nullable=True)
    full_name = Column(String, nullable=False)
    contact_method = Column(String, nullable=False, default="phone")
    contact_value = Column(String, nullable=False)
    note = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="requested", index=True)  # requested | contacted | converted | cancelled
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    service = relationship("Service")
    patient = relationship("PatientLead")


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
    """Outbox for one reminder on one channel.

    A row exists as soon as we try, not only when we succeed. Recording attempts
    is what bounds the retries: this table is also the scheduler's "already
    handled?" check, so with success-only rows a permanently failing send is
    retried on every tick forever — cheap while nothing is configured, expensive
    the moment a real SMS gateway is charging per attempt.
    """
    __tablename__ = "reminder_logs"

    id = Column(Integer, primary_key=True, index=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String, nullable=False)  # 24h | 2h | manual
    # phone | email. The unit of retry: a patient with both should still get the
    # email when SMS is failing, and vice versa, so each is tracked separately.
    medium = Column(String, nullable=False, default="phone", index=True)
    # email | zns | sms | sms_sandbox | none. sms_sandbox and mock sends are
    # real flow runs that never reached a handset — never count them as delivery.
    channel = Column(String, nullable=False)
    status = Column(String, nullable=False, default="sent")  # sent | failed
    attempts = Column(Integer, nullable=False, default=1)
    last_error = Column(Text, nullable=True)
    sent_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


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


class FeatureFlag(Base):
    """One on/off switch. See services/features.py for the keys and resolution.

    clinic_id NULL means the vendor-wide default; a row with a clinic_id
    overrides it for that clinic only.
    """
    __tablename__ = "feature_flags"
    __table_args__ = (
        UniqueConstraint("clinic_id", "key", name="uq_feature_flag_scope"),
    )

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"),
                       nullable=True, index=True)
    key = Column(String, nullable=False, index=True)
    enabled = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())
