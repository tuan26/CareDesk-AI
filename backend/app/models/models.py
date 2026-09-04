from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Date, DateTime, Time, ForeignKey,
    Text, JSON, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.app.core import clock
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
    created_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())

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
    created_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())


class Organization(Base):
    """A chain / group that owns multiple clinics. Enables cross-clinic roll-up."""
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=True)  # public link /g/<slug>
    landing_enabled = Column(Boolean, default=True, nullable=False)  # chain landing page at /book/<slug>
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())

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
    created_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())


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
    # The North Star. Asked at onboarding because a clinic cannot recall it two
    # months later, and without a "before" the cohort rate proves nothing.
    baseline_return_percent = Column(Float, nullable=True)
    baseline_captured_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())

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
    # Getting there. A street address is not directions: patients overwhelmingly
    # want a tap that opens their map app. map_url is whatever the clinic pastes
    # (a Google Maps share link); lat/lng additionally feed schema.org geo so the
    # location can appear as a rich result.
    map_url = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
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
    #: How long after a visit this service is normally repeated, in days.
    #: NULL means "one-off, never chase a revisit" — the safe default, because a
    #: wrong number here turns into the clinic pestering someone who was never
    #: due back. Set per service by the clinic; nothing infers it.
    revisit_interval_days = Column(Integer, nullable=True)

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


class DoctorTimeOff(Base):
    """Leave, public holidays, an afternoon off.

    WorkingSchedule says which weekdays a doctor works, which is true forever
    once entered. This is the exception to it. Without it the AI cheerfully
    books patients through Tết, and the clinic finds out when someone arrives
    to a locked door — which is the kind of incident that gets the AI switched
    off for good.
    """
    __tablename__ = "doctor_time_off"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    # NULL = the whole clinic is closed (public holiday, Tết). One row instead of
    # one per doctor, so nobody is forgotten.
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE"),
                       nullable=True, index=True)
    start_date = Column(Date, nullable=False, index=True)
    end_date = Column(Date, nullable=False, index=True)   # inclusive
    # NULL/NULL = the whole day. Set both for a half day ("nghỉ chiều thứ 5").
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    reason = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())

    doctor = relationship("Doctor")

    @property
    def is_full_day(self) -> bool:
        return self.start_time is None or self.end_time is None


class PatientLead(Base):
    __tablename__ = "patient_leads"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=True, index=True)
    full_name = Column(String, nullable=False)
    phone = Column(String, index=True, nullable=True)
    email = Column(String, nullable=True)
    # HOW they first reached us. Distinct from Appointment.booking_source, which
    # says who typed the booking in. Conflating the two answers neither question:
    # "did the AI book this?" and "which advert paid for this patient?" have
    # different answers and different owners.
    source = Column(String, default="web")  # web | web_form | zalo | facebook | staff

    # --- First touch -----------------------------------------------------
    # Captured on the first page view and never overwritten. Last-touch is the
    # easy thing to record and the wrong thing to report: the retargeting ad
    # that caught someone on their way back gets credit for a patient the
    # original campaign found, so the channel that actually works looks worse
    # than the one that finished the job.
    utm_source = Column(String, nullable=True, index=True)     # facebook | google | tiktok
    utm_medium = Column(String, nullable=True)                 # cpc | organic | qr
    utm_campaign = Column(String, nullable=True, index=True)   # "pico-thang-8"
    utm_content = Column(String, nullable=True)                # which creative
    utm_term = Column(String, nullable=True)                   # search keyword
    click_id = Column(String, nullable=True)                   # fbclid / gclid / ttclid
    referrer = Column(String, nullable=True)                   # where they came from
    landing_path = Column(String, nullable=True)               # which page caught them
    first_seen_at = Column(DateTime(timezone=True), nullable=True)

    # --- Latest touch ----------------------------------------------------
    # Overwritten on every visit, and deliberately never used for acquisition
    # credit. It answers a different question: which touchpoint brought them
    # back on the day they finally converted. Keeping both means assisted
    # conversion can be analysed later without disturbing the original
    # attribution — the first-touch fields above stay immutable once set.
    latest_utm_source = Column(String, nullable=True, index=True)
    latest_utm_medium = Column(String, nullable=True)
    latest_utm_campaign = Column(String, nullable=True)
    latest_landing_path = Column(String, nullable=True)
    latest_touch_at = Column(DateTime(timezone=True), nullable=True)
    touch_count = Column(Integer, nullable=False, default=1)
    external_id = Column(String, index=True, nullable=True)  # user id on Zalo/Facebook
    consent_given = Column(Boolean, default=False)
    consent_timestamp = Column(DateTime(timezone=True), nullable=True)
    note = Column(Text, nullable=True)  # CRM note by staff
    tags = Column(JSON, nullable=True)  # e.g. ["VIP", "Liệu trình mụn"]
    referral_code = Column(String, index=True, nullable=True)  # this patient's own code to share
    referred_by_patient_id = Column(Integer, ForeignKey("patient_leads.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())

    appointments = relationship("Appointment", back_populates="patient")
    conversations = relationship("Conversation", back_populates="patient", cascade="all, delete-orphan")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=True, index=True)
    patient_id = Column(Integer, ForeignKey("patient_leads.id", ondelete="CASCADE"), nullable=False)
    channel = Column(String, default="web")  # web | zalo | facebook
    status = Column(String, default="bot_active")  # bot_active | handoff_requested | agent_active
    # Why a human was called for. Decides whether the assistant may keep
    # answering while the queue is unattended: after a safety trigger it must
    # not, after "em không có thông tin đó" silence is worse than an answer.
    # See core/handoff.py.
    handoff_reason = Column(String, nullable=True)
    locale = Column(String, nullable=True)  # Explicit patient locale; NULL uses Clinic.default_locale
    # Which location the patient arrived from (/chat/<brand>/<branch>). Without
    # it the booking flow just took the first doctor with a free slot, so every
    # conversation ended up booking whichever branch that doctor happened to
    # work at, no matter which one the patient clicked.
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="SET NULL"), nullable=True, index=True)
    booking_state = Column(JSON, nullable=True)  # AI booking flow state machine
    created_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now(), onupdate=func.now())

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
    created_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    conversation = relationship("Conversation", back_populates="public_sessions")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    sender = Column(String, nullable=False)  # patient | bot | agent
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())
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
    # Queue timestamps. Deliberately NOT new status values: status already drives
    # slot occupancy, revenue and reminders, and adding "arrived"/"in_progress"
    # there would ripple through all three. The queue state is derived from these
    # two instead — see api/endpoints/queue.py.
    arrived_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)

    # --- Lifecycle -------------------------------------------------------
    # Marketing and operations disagree about what "a booking" means, and both
    # are right. Analytics counts a booking the moment the patient asked, so a
    # channel is never penalised for how long the clinic took to call back.
    # Operations needs the whole chain, and the gap between the first two is a
    # KPI in its own right: "you are losing bookings because confirmation takes
    # four hours" is a fixable problem that looks like a bad ad campaign.
    booking_requested_at = Column(DateTime(timezone=True), nullable=True)
    booking_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    note = Column(Text, nullable=True)
    booking_source = Column(String, default="staff")  # staff | ai_chat | ai_followup | campaign | referral
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())

    patient = relationship("PatientLead", back_populates="appointments")
    service = relationship("Service", back_populates="appointments")
    doctor = relationship("Doctor", back_populates="appointments")
    branch = relationship("Branch", back_populates="appointments")


class VisitRecord(Base):
    """What happened at one visit. Deliberately light.

    Not an EMR. Prescriptions are absent on purpose: Vietnam has specific rules
    for electronic prescriptions, and a half-built one is a legal risk the clinic
    would carry while blaming the software. What is here is the minimum a
    dermatology/aesthetics clinic needs to answer "what did we do last time, and
    what did we agree next" — plus the photos, which for this speciality are both
    the record and the strongest sales asset the clinic owns.

    One row per appointment: the visit is the unit, not the patient.
    """
    __tablename__ = "visit_records"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id", ondelete="CASCADE"),
                            nullable=False, unique=True, index=True)
    patient_id = Column(Integer, ForeignKey("patient_leads.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True)

    chief_complaint = Column(Text, nullable=True)   # khách than phiền gì
    findings = Column(Text, nullable=True)          # bác sĩ ghi nhận
    treatment_done = Column(Text, nullable=True)    # đã làm gì hôm nay
    advice = Column(Text, nullable=True)            # dặn dò về nhà
    # Feeds the recall automation: the doctor's own judgement beats a fixed
    # 30-day rule, because a laser course and a routine check are not the same.
    next_visit_days = Column(Integer, nullable=True)

    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now(), onupdate=func.now())

    photos = relationship("VisitPhoto", back_populates="visit",
                          cascade="all, delete-orphan")
    appointment = relationship("Appointment")
    patient = relationship("PatientLead")
    doctor = relationship("Doctor")


class VisitPhoto(Base):
    """A before/after photo.

    `stored_name` is an unguessable filename, never the original one: these are
    photographs of patients' faces and bodies, so the path must not be derivable
    from a patient id or a sequence. They are served only through an
    authenticated, clinic-scoped endpoint — never from a static mount.

    Publishing one to the public site is a separate, explicit act: see the
    consent columns below. A clinical record and a marketing asset are the same
    file but not the same permission.
    """
    __tablename__ = "visit_photos"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    visit_record_id = Column(Integer, ForeignKey("visit_records.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    kind = Column(String, nullable=False, default="after")   # before | after
    stored_name = Column(String, nullable=False, unique=True)
    original_name = Column(String, nullable=True)
    content_type = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    caption = Column(String, nullable=True)
    uploaded_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())

    # --- Publishing to the public site ---------------------------------
    # Three separate facts, deliberately not collapsed into one flag:
    #
    #   consent_given_at  the patient agreed. Withdrawable — clearing this must
    #                     take the photo off the site immediately.
    #   consent_by        which staff member recorded that agreement, so the
    #                     clinic can answer "who says she agreed?" two years on.
    #   is_published      the clinic chose to show this particular one.
    #
    # A photo appears publicly only when consent AND publication are both true.
    # Defaults are off: a clinical record must never become marketing by accident.
    consent_given_at = Column(DateTime(timezone=True), nullable=True)
    consent_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    consent_note = Column(String, nullable=True)      # e.g. "ký giấy đồng ý 12/08"
    is_published = Column(Boolean, nullable=False, default=False)
    # Groups a before with its after into one public case.
    showcase_group = Column(String, nullable=True, index=True)
    public_title = Column(String, nullable=True)      # "Trị nám sau 3 buổi"

    visit = relationship("VisitRecord", back_populates="photos")

    @property
    def is_publicly_visible(self) -> bool:
        return bool(self.is_published and self.consent_given_at)


class BookingRequest(Base):
    """Administrative request only; staff/calendar integration creates an Appointment later."""
    __tablename__ = "booking_requests"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    patient_id = Column(Integer, ForeignKey("patient_leads.id", ondelete="SET NULL"), nullable=True, index=True)
    service_id = Column(Integer, ForeignKey("services.id", ondelete="SET NULL"), nullable=True, index=True)
    # Which location, and which doctor was offered. Both are known when the
    # request is made — the chat pins a branch and names a doctor before quoting
    # times — and both used to be dropped, so the receptionist saw a request with
    # no clinic and no doctor and had to reopen the conversation to find out.
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="SET NULL"), nullable=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True, index=True)
    locale = Column(String, nullable=False, default="vi")
    service_or_need = Column(Text, nullable=False)
    #: When the patient asked to come, as a real timestamp. preferred_time stays
    #: for what they actually said — "chiều thứ 5 nào cũng được" is a legitimate
    #: answer that no column can hold.
    preferred_at = Column(DateTime(timezone=True), nullable=True, index=True)
    preferred_time = Column(String, nullable=True)
    full_name = Column(String, nullable=False)
    contact_method = Column(String, nullable=False, default="phone")
    contact_value = Column(String, nullable=False)
    note = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="requested", index=True)  # requested | contacted | converted | cancelled
    created_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())

    service = relationship("Service")
    patient = relationship("PatientLead")
    branch = relationship("Branch")
    doctor = relationship("Doctor")


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
    updated_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now(), onupdate=func.now())


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
    sent_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now(), onupdate=func.now())


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
    created_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())


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
    created_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())


class ScheduledAction(Base):
    __tablename__ = "scheduled_actions"

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=True, index=True)
    rule_id = Column(Integer, ForeignKey("automation_rules.id", ondelete="CASCADE"), nullable=True)
    patient_id = Column(Integer, ForeignKey("patient_leads.id", ondelete="CASCADE"), nullable=True, index=True)
    due_at = Column(DateTime(timezone=True), nullable=False, index=True)
    status = Column(String, default="pending", index=True)  # pending | sent | cancelled | failed
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())
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
    recorded_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())


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
    purchased_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())
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
    created_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())
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
    created_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())
    notified_at = Column(DateTime(timezone=True), nullable=True)

    patient = relationship("PatientLead")
    service = relationship("Service")


class SiteContent(Base):
    """Editable copy for a clinic's public site, as key -> JSON value.

    A table of keys rather than a column per field, because the landing page will
    keep growing sections and each one would otherwise be a migration plus a
    schema change plus a deploy. Keys are declared in services/site_content.py
    with their defaults, so an unset key still renders sensible Vietnamese copy
    instead of a blank page.

    Only *copy* lives here. Services, doctors, photos and reviews stay in their
    own tables — they are operational records that the site happens to display,
    not website content someone has to maintain twice.
    """
    __tablename__ = "site_content"
    __table_args__ = (
        UniqueConstraint("clinic_id", "key", name="uq_site_content_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    key = Column(String, nullable=False, index=True)
    value = Column(JSON, nullable=True)
    updated_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now(),
                        onupdate=func.now())
    updated_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


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
    sent_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())
    answered_at = Column(DateTime(timezone=True), nullable=True)

    # Publishing a review is the clinic's decision, one at a time. Never
    # automatic on a 5-star: the patient wrote it for the clinic, not for a
    # website, and a real name on a public page is personal data.
    is_published = Column(Boolean, nullable=False, default=False)
    public_name = Column(String, nullable=True)   # "Chị Ngọc A." — never the full record name
    published_at = Column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String, nullable=False)  # e.g. "create_appointment"
    details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())

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
    updated_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now(),
                        onupdate=func.now())


class RevenueOpportunity(Base):
    """Money the clinic has probably already lost, written down as a row.

    Everything else in this schema records what *did* happen: an appointment
    that exists, revenue that was taken. This records what should have happened
    and did not — a patient overdue for a revisit, a course of treatment
    abandoned halfway, a package about to expire with sessions unused, a booking
    request nobody rang back.

    Two fields carry the weight and both are deliberately conservative:

    ``estimated_value`` is only ever derived from a number the clinic itself
    entered — a service price, what they actually paid for a package. Nothing is
    invented, because the whole product rests on the owner believing this figure.

    ``probability`` starts from a documented base rate per type and switches to
    this clinic's *own* observed conversion once enough opportunities of that
    type have resolved. ``reasons`` records what moved it, so the screen can
    explain itself rather than showing an oracle's number.

    ``is_holdout`` is what makes "recovered revenue" an honest claim instead of
    a flattering one. A slice of opportunities is deliberately never contacted;
    the difference in conversion between contacted and held-out is the only part
    of the money that CareDesk can take credit for. Without it we would be
    counting patients who were coming back anyway.
    """
    __tablename__ = "revenue_opportunities"
    __table_args__ = (
        # One open opportunity per (patient, type, subject). Re-running detection
        # must not stack duplicates on the same patient every night.
        UniqueConstraint("clinic_id", "opportunity_type", "patient_id", "dedupe_key",
                         name="uq_revenue_opportunity_subject"),
    )

    id = Column(Integer, primary_key=True, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("patient_leads.id", ondelete="CASCADE"),
                        nullable=False, index=True)

    #: See services/revenue_recovery.py for the six detectors.
    opportunity_type = Column(String, nullable=False, index=True)
    #: Distinguishes two opportunities of the same type for the same patient —
    #: the package id, the service id, the booking request id. Never NULL
    #: (SQLite and Postgres both let NULLs slip past a unique constraint).
    dedupe_key = Column(String, nullable=False, default="")

    # What it is about. All optional: a lost lead has no package, an expiring
    # package has no booking request.
    service_id = Column(Integer, ForeignKey("services.id", ondelete="SET NULL"), nullable=True)
    patient_package_id = Column(Integer, ForeignKey("patient_packages.id", ondelete="SET NULL"), nullable=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True)
    booking_request_id = Column(Integer, ForeignKey("booking_requests.id", ondelete="SET NULL"), nullable=True)

    estimated_value = Column(Float, nullable=False, default=0.0)
    probability = Column(Float, nullable=False, default=0.0)   # 0..1
    #: Days overdue / days until the money is gone. Drives urgency in the queue.
    urgency_days = Column(Integer, nullable=False, default=0)
    #: Human-readable evidence: [{"code": ..., "text": ..., "weight": ...}]
    reasons = Column(JSON, nullable=True)

    # What to do about it — the Next Best Action, resolved at detection time.
    recommended_channel = Column(String, nullable=True)   # zalo | sms | call
    recommended_message = Column(Text, nullable=True)
    recommended_offer = Column(String, nullable=True)

    status = Column(String, nullable=False, default="open", index=True)
    # open | contacted | recovered | lost | dismissed | expired
    is_holdout = Column(Boolean, nullable=False, default=False, index=True)

    detected_at = Column(DateTime(timezone=True), default=clock.now, server_default=func.now())
    contacted_at = Column(DateTime(timezone=True), nullable=True)
    #: Set when the patient acted. The appointment/revenue that closed the loop.
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_appointment_id = Column(Integer, ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True)
    recovered_amount = Column(Float, nullable=True)
    #: Why it was lost, filled in by staff. Free text is useless in aggregate,
    #: so this is a closed list — see LOSS_REASONS.
    loss_reason = Column(String, nullable=True)

    patient = relationship("PatientLead", foreign_keys=[patient_id])
    service = relationship("Service", foreign_keys=[service_id])
