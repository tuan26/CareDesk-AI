import asyncio
import os
import sys
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from backend.app.core.config import settings
from backend.app.core.logging_config import setup_logging
from backend.app.core.database import engine
from backend.app.core.migrate import run_migrations
from backend.app.core.seed import seed_db
from backend.app.api.endpoints import (
    auth, clinic, appointment, chat, webhooks, reports, public, ws,
        packages, automations, copilot, platform, org, booking_requests, landing, seo,
        onboarding, visits, content
)
from backend.app.services.ws_manager import ws_manager
from backend.app.services.reminder import reminder_loop

setup_logging()
logger = logging.getLogger(__name__)

# Fail fast on misconfiguration that would otherwise silently weaken
# production security. Checked at import time, before the app (and its
# permissive-looking CORS middleware) is even constructed.
if settings.is_production and "*" in settings.cors_origins_list:
    raise RuntimeError(
        "BACKEND_CORS_ORIGINS='*' is not allowed when ENVIRONMENT=production. "
        "Set explicit, comma-separated origins instead."
    )
if settings.is_production and "SUPER_SECRET_KEY" in settings.SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY is still the default placeholder. Set a real SECRET_KEY "
        "env var before running with ENVIRONMENT=production."
    )
if settings.is_production and (settings.SMS_PROVIDER == "mock" or settings.SMS_SANDBOX):
    # A simulated sender in production is the worst of both worlds: the clinic
    # sees reminders marked as handled while no patient is reached, and nothing
    # on screen looks wrong. Sandbox belongs on staging.
    raise RuntimeError(
        "SMS_PROVIDER=mock hoặc SMS_SANDBOX đang bật với ENVIRONMENT=production. "
        "Tin nhắn sẽ KHÔNG tới tay bệnh nhân. Dùng nhà cung cấp thật, hoặc để "
        "SMS_PROVIDER trống nếu chưa có tài khoản — hệ thống sẽ báo rõ là chưa "
        "gửi được thay vì giả vờ đã gửi."
    )
if settings.is_production and "localhost" in settings.PUBLIC_BASE_URL:
    # Every canonical link, og:url and sitemap entry is built from this. Left at
    # localhost, Facebook/Zalo previews and Google's index point at nothing.
    raise RuntimeError(
        "PUBLIC_BASE_URL still points at localhost. Set it to the real public "
        "domain before running with ENVIRONMENT=production — canonical URLs, "
        "og:url and sitemap.xml are all derived from it."
    )

# Initialize FastAPI app
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    description="CareDesk AI - Trợ lý lễ tân ảo AI phòng khám da liễu & thẩm mỹ da"
)

# Set CORS origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Windows console may use a legacy codepage (cp932/cp1252) that cannot print
# Vietnamese log lines - never let a log statement crash a request.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Startup: apply migrations, seed data, wire realtime + reminder scheduler
@app.on_event("startup")
async def startup_db_setup():
    if not settings.is_production and "SUPER_SECRET_KEY" in settings.SECRET_KEY:
        logger.warning(
            "SECRET_KEY dang dung gia tri mac dinh. Bat buoc dat bien moi "
            "truong SECRET_KEY khi chay production!"
        )

    logger.info("Initializing database...")
    run_migrations()
    setup_logging()  # alembic's fileConfig just reset root logging - restore it
    seed_db()
    logger.info("Database initialization completed.")

    # The reminder scheduler and the in-memory rate limiter both keep their
    # state in this process. Running more than one uvicorn worker means each
    # worker runs its own scheduler (duplicate reminders/digests) and its own
    # rate-limit counters (limits effectively multiply by worker count).
    worker_count = os.getenv("WEB_CONCURRENCY") or os.getenv("UVICORN_WORKERS")
    if worker_count and int(worker_count) > 1 and settings.ENABLE_REMINDER_SCHEDULER:
        logger.warning(
            "ENABLE_REMINDER_SCHEDULER is on with %s workers configured. The "
            "reminder scheduler and rate limiter are single-process/in-memory: "
            "each worker will run its own scheduler and duplicate reminders/"
            "digests, and rate limits apply per-worker. Run a single worker, "
            "or disable the scheduler on all but one and move rate limiting "
            "to a shared store (e.g. Redis) before scaling out.",
            worker_count,
        )

    # Realtime inbox: give the WS manager the running event loop
    ws_manager.set_loop(asyncio.get_running_loop())

    # Automatic appointment reminders (24h / 2h before start)
    if settings.ENABLE_REMINDER_SCHEDULER:
        asyncio.create_task(reminder_loop())

# Include Routers
app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["Authentication"])
app.include_router(clinic.router, prefix=f"{settings.API_V1_STR}/clinic", tags=["Clinic Setup"])
app.include_router(appointment.router, prefix=f"{settings.API_V1_STR}/appointments", tags=["Appointment Engine"])
app.include_router(chat.router, prefix=f"{settings.API_V1_STR}/chat", tags=["AI & Inbox Chat"])
app.include_router(webhooks.router, prefix=f"{settings.API_V1_STR}/webhooks", tags=["Channel Webhooks"])
app.include_router(reports.router, prefix=f"{settings.API_V1_STR}/reports", tags=["Business Reports"])
app.include_router(public.router, prefix=f"{settings.API_V1_STR}/public", tags=["Public Links"])
app.include_router(ws.router, prefix=f"{settings.API_V1_STR}/ws", tags=["Realtime"])
app.include_router(packages.router, prefix=f"{settings.API_V1_STR}/packages", tags=["Service Packages"])
app.include_router(automations.router, prefix=f"{settings.API_V1_STR}/automations", tags=["Revenue Automations"])
app.include_router(copilot.router, prefix=f"{settings.API_V1_STR}/copilot", tags=["Staff Copilot"])
app.include_router(platform.router, prefix=f"{settings.API_V1_STR}/platform", tags=["Platform Super-Admin"])
app.include_router(org.router, prefix=f"{settings.API_V1_STR}/org", tags=["Organization / Chain"])
app.include_router(booking_requests.router, prefix=f"{settings.API_V1_STR}/booking-requests", tags=["Booking Requests"])
app.include_router(onboarding.router, prefix=f"{settings.API_V1_STR}/onboarding", tags=["Onboarding"])
app.include_router(visits.router, prefix=f"{settings.API_V1_STR}/visits", tags=["Queue & Visit Records"])
app.include_router(content.router, prefix=f"{settings.API_V1_STR}/content", tags=["Website Content"])

# Public landing pages are server-rendered HTML for crawlers, so they live at
# /book/* rather than under the JSON API prefix. nginx/vite proxy this path to
# the backend; everything else still goes to the SPA.
app.include_router(landing.router, prefix="/book", tags=["Public Landing"])

# robots.txt / sitemap.xml live at the site root, so they are mounted
# without a prefix (and proxied there by nginx/vite).
app.include_router(seo.router, tags=["SEO"])

@app.get("/")
def read_root():
    return {
        "message": "Welcome to CareDesk AI API",
        "version": "2.0.0",
        "docs_url": "/docs"
    }

@app.get("/health")
def health_check():
    """Liveness/readiness probe: confirms the process can actually reach the DB."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"database unavailable: {e}")
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    reload = not settings.is_production
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=reload)
