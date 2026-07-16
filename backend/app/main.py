from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.core.config import settings
from backend.app.core.database import engine, Base
from backend.app.core.seed import seed_db
from backend.app.api.endpoints import auth, clinic, appointment, chat

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

# Startup event to create tables and seed database
@app.on_event("startup")
def startup_db_setup():
    print("Initializing Database...")
    Base.metadata.create_all(bind=engine)
    seed_db()
    print("Database initialization completed!")

# Include Routers
app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["Authentication"])
app.include_router(clinic.router, prefix=f"{settings.API_V1_STR}/clinic", tags=["Clinic Setup"])
app.include_router(appointment.router, prefix=f"{settings.API_V1_STR}/appointments", tags=["Appointment Engine"])
app.include_router(chat.router, prefix=f"{settings.API_V1_STR}/chat", tags=["AI & Inbox Chat"])

@app.get("/")
def read_root():
    return {
        "message": "Welcome to CareDesk AI API",
        "version": "1.0.0",
        "docs_url": "/docs"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=True)
