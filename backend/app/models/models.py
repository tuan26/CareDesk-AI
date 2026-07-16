from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Time, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.app.core.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String, default="receptionist")  # admin | owner | receptionist
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    audit_logs = relationship("AuditLog", back_populates="user")


class Clinic(Base):
    __tablename__ = "clinics"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    logo_url = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    address = Column(String, nullable=True)
    cancellation_policy = Column(Text, nullable=True)
    
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
    full_name = Column(String, nullable=False)
    phone = Column(String, index=True, nullable=True)
    email = Column(String, nullable=True)
    source = Column(String, default="web")  # web | zalo | facebook
    consent_given = Column(Boolean, default=False)
    consent_timestamp = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    appointments = relationship("Appointment", back_populates="patient")
    conversations = relationship("Conversation", back_populates="patient", cascade="all, delete-orphan")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patient_leads.id", ondelete="CASCADE"), nullable=False)
    channel = Column(String, default="web")  # web | zalo | facebook
    status = Column(String, default="bot_active")  # bot_active | handoff_requested | agent_active
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
    patient_id = Column(Integer, ForeignKey("patient_leads.id", ondelete="CASCADE"), nullable=False)
    service_id = Column(Integer, ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    status = Column(String, default="pending")  # pending | confirmed | cancelled | completed | no_show
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    patient = relationship("PatientLead", back_populates="appointments")
    service = relationship("Service", back_populates="appointments")
    doctor = relationship("Doctor", back_populates="appointments")
    branch = relationship("Branch", back_populates="appointments")


class AISafetyRule(Base):
    __tablename__ = "ai_safety_rules"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, nullable=False)  # urgent | clinical_diagnosis | pediatric | pregnancy | medication
    keyword_pattern = Column(String, nullable=False)  # comma separated or regex keywords
    fallback_message = Column(Text, nullable=False)
    force_handoff = Column(Boolean, default=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String, nullable=False)  # e.g. "create_appointment"
    details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="audit_logs")
