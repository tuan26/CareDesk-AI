import os
from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

# Read once so every default below agrees on dev vs. production behavior.
_ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
_SEED_DEMO_DATA_RAW = os.getenv("SEED_DEMO_DATA")

# backend/app/core/config.py -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _absolutise_sqlite(url: str) -> str:
    """Pin a relative sqlite path to the repo root instead of the process CWD.

    'sqlite:///./caredesk.db' resolves against whatever directory the process
    was started from, so `uvicorn` from the repo root and `alembic` from
    backend/ silently used two different database files - migrations landed on
    an empty copy while the real data sat untouched. Anchoring to the repo root
    makes the same URL mean the same file from any CWD.
    """
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return url  # postgres/mysql/... - not a filesystem path
    path = url[len(prefix):]
    if not path or path.startswith(":memory:"):
        return url
    if Path(path).is_absolute():
        return url
    return f"{prefix}{(_REPO_ROOT / path).resolve().as_posix()}"

class Settings(BaseSettings):
    PROJECT_NAME: str = "CareDesk AI"
    API_V1_STR: str = "/api/v1"

    # development | production. Gates demo-data seeding and several hard-fail
    # safety checks at startup (default SECRET_KEY, wildcard CORS, ...).
    ENVIRONMENT: str = _ENVIRONMENT

    # Database configuration (Defaults to SQLite for local development convenience)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./caredesk.db")

    # SQLAlchemy connection pool. Left at library defaults (pool_size=5,
    # max_overflow=10, i.e. 15 total connections, pool_timeout=30s) a load
    # test at 100 concurrent requests saturated the pool almost immediately -
    # every endpoint that touches the DB (including unrelated ones sharing
    # the same pool) stalled for up to 30s waiting for a connection, then
    # errored with "QueuePool limit ... connection timed out". Size for your
    # expected concurrent request volume; Postgres/production should raise
    # these well past the defaults.
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "20"))
    DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", "20"))
    DB_POOL_TIMEOUT: int = int(os.getenv("DB_POOL_TIMEOUT", "30"))

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

    # CORS Origins. Comma-separated via env; defaults to the local Vite dev
    # server only. "*" is rejected outright when ENVIRONMENT=production
    # (checked at startup in main.py). Kept as a plain str field — declaring
    # it list[str] makes pydantic-settings expect JSON-encoded env values
    # ('["a","b"]'), which breaks a plain comma-separated BACKEND_CORS_ORIGINS.
    BACKEND_CORS_ORIGINS: str = os.getenv(
        "BACKEND_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    )

    # SaaS Plans (bot replies per month)
    PLAN_FREE_QUOTA: int = 200
    PLAN_PRO_QUOTA: int = 5000

    # Reminder scheduler
    ENABLE_REMINDER_SCHEDULER: bool = os.getenv("ENABLE_REMINDER_SCHEDULER", "true").lower() == "true"
    REMINDER_CHECK_INTERVAL_SECONDS: int = 60
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")

    # Where the React app is served. In production this is the same host as
    # PUBLIC_BASE_URL — Vercel serves the SPA and rewrites /book/* here — so the
    # default is correct there and the setting can be ignored.
    #
    # In development they are two different ports: the landing pages are rendered
    # by this process on :8000 while the SPA runs on Vite's :5173. A relative
    # "/chat/<slug>" link on a landing page then resolves against :8000 and 404s.
    # Defaulting to the Vite port in non-production makes "Đặt lịch với trợ lý ảo"
    # work out of the box instead of every developer hitting the same dead link.
    FRONTEND_BASE_URL: str = os.getenv(
        "FRONTEND_BASE_URL",
        "http://localhost:5173"
        if _ENVIRONMENT != "production"
        and "localhost" in os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
        else os.getenv("PUBLIC_BASE_URL", "http://localhost:8000"),
    )

    # Where patient photos are written. Local disk by default, which is fine on
    # a single box but is EPHEMERAL on most PaaS: a redeploy wipes it and the
    # records point at files that no longer exist. Mount a persistent volume, or
    # move to object storage, before a clinic relies on before/after photos.
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", str(_REPO_ROOT / "uploads"))

    # SMS/ZNS gateway (mock when empty)
    # SMS is the fallback when a clinic has no approved Zalo ZNS template (which
    # is the common case early on, since ZNS approval takes days-to-weeks).
    # Leave SMS_PROVIDER empty and NOTHING reaches a patient's phone — the
    # dashboard warns about this rather than pretending reminders were sent.

    # How long a slot stays held while the patient pays the deposit. Too short
    # and people lose the slot mid-transfer; too long and one abandoned payment
    # blocks a prime evening slot all day.
    DEPOSIT_HOLD_MINUTES: int = int(os.getenv("DEPOSIT_HOLD_MINUTES", "15"))

    # "esms" | "speedsms" | "mock" | "". "mock" needs no account and logs
    # instead of sending — for local dev. Deployment config, not a per-clinic
    # feature flag: which gateway the process talks to is a property of the
    # environment, and a clinic must never be able to switch itself into a
    # sandbox and stop reaching its own patients.
    SMS_PROVIDER: str = os.getenv("SMS_PROVIDER", "")
    SMS_API_KEY: str = os.getenv("SMS_API_KEY", "")
    SMS_SECRET_KEY: str = os.getenv("SMS_SECRET_KEY", "")    # eSMS only
    SMS_BRANDNAME: str = os.getenv("SMS_BRANDNAME", "")      # registered sender name
    # eSMS sandbox: the request is validated and answered normally but the
    # message is not stored, not charged and not delivered. Better than the mock
    # for staging because it exercises real credentials and real error paths.
    # No confirmed equivalent exists for SpeedSMS, so this only affects eSMS.
    SMS_SANDBOX: bool = os.getenv("SMS_SANDBOX", "false").lower() in ("1", "true", "yes")


    # Rate limiting for public endpoints (requests per minute per IP)
    RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))

    # Public web-chat credentials. Keep enforcement opt-in while old embedded widgets migrate.
    PUBLIC_CHAT_SESSION_TTL_SECONDS: int = int(os.getenv("PUBLIC_CHAT_SESSION_TTL_SECONDS", str(60 * 60 * 24)))
    # How long a browser may pick its own conversation back up. Beyond this a
    # fortnight-old exchange is clutter rather than context, and its
    # half-finished booking points at dates that have passed.
    PUBLIC_CHAT_RESUME_MAX_AGE_HOURS: int = int(os.getenv("PUBLIC_CHAT_RESUME_MAX_AGE_HOURS", "72"))

    # Demo/sample data (accounts, demo clinic, demo chain) — on by default in
    # dev so `python -m backend.app.main` stays a one-command demo, off by
    # default in production so a fresh prod DB doesn't get seeded with
    # publicly-known demo credentials. Override explicitly with SEED_DEMO_DATA.
    SEED_DEMO_DATA: bool = (
        _SEED_DEMO_DATA_RAW.strip().lower() == "true"
        if _SEED_DEMO_DATA_RAW is not None
        else _ENVIRONMENT != "production"
    )

    # Platform (vendor/publisher) super-admin bootstrap account. If left
    # blank in production, a random password is generated at first boot and
    # logged once — see seed.py.
    PLATFORM_ADMIN_EMAIL: str = os.getenv("PLATFORM_ADMIN_EMAIL", "")
    PLATFORM_ADMIN_PASSWORD: str = os.getenv("PLATFORM_ADMIN_PASSWORD", "")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

    # Applies to the .env value too, not just the default above.
    _fix_sqlite_path = field_validator("DATABASE_URL")(lambda v: _absolutise_sqlite(v))

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.BACKEND_CORS_ORIGINS.split(",") if o.strip()]

settings = Settings()
