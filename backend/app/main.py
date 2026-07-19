import asyncio
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.core.config import settings
from backend.app.core.database import engine, Base
from backend.app.core.seed import seed_db
from backend.app.api.endpoints import (
    auth, clinic, appointment, chat, webhooks, reports, public, ws,
    packages, automations, copilot, platform, org
)
from backend.app.services.ws_manager import ws_manager
from backend.app.services.reminder import reminder_loop

# Initialize FastAPI app
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    description="CareDesk AI - Trợ lý lễ tân ảo AI phòng khám da liễu & thẩm mỹ da"
)

# Set CORS origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
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

# Startup: create tables, seed data, wire realtime + reminder scheduler
@app.on_event("startup")
async def startup_db_setup():
    if "SUPER_SECRET_KEY" in settings.SECRET_KEY:
        print("[SECURITY WARNING] SECRET_KEY dang dung gia tri mac dinh. "
              "Bat buoc dat bien moi truong SECRET_KEY khi chay production!")

    print("Initializing Database...")
    Base.metadata.create_all(bind=engine)
    seed_db()
    print("Database initialization completed!")

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

@app.get("/")
def read_root():
    return {
        "message": "Welcome to CareDesk AI API",
        "version": "2.0.0",
        "docs_url": "/docs"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=True)
