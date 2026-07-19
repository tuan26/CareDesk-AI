import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "CareDesk AI"
    API_V1_STR: str = "/api/v1"
    
    # Database configuration (Defaults to SQLite for local development convenience)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./caredesk.db")
    
    # Security config
    SECRET_KEY: str = os.getenv("SECRET_KEY", "SUPER_SECRET_KEY_CHANGE_THIS_IN_PRODUCTION_123456789")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    
    # AI Config
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-5.6-terra")
    
    # Email Reminder Config
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    EMAILS_FROM_EMAIL: str = os.getenv("EMAILS_FROM_EMAIL", "no-reply@caredesk.ai")
    EMAILS_FROM_NAME: str = os.getenv("EMAILS_FROM_NAME", "CareDesk AI Receptionist")
    
    # CORS Origins
    BACKEND_CORS_ORIGINS: list[str] = ["*"]

    # SaaS Plans (bot replies per month)
    PLAN_FREE_QUOTA: int = 200
    PLAN_PRO_QUOTA: int = 5000

    # Reminder scheduler
    ENABLE_REMINDER_SCHEDULER: bool = os.getenv("ENABLE_REMINDER_SCHEDULER", "true").lower() == "true"
    REMINDER_CHECK_INTERVAL_SECONDS: int = 60
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")

    # SMS/ZNS gateway (mock when empty)
    SMS_API_KEY: str = os.getenv("SMS_API_KEY", "")

    # Rate limiting for public endpoints (requests per minute per IP)
    RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

settings = Settings()
