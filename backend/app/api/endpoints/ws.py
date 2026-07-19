"""
Realtime WebSocket endpoint for the staff inbox.
Clients connect with their JWT: ws://host/api/v1/ws/inbox?token=...
and receive JSON events (message / handoff / status / appointment_update).
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import jwt, JWTError
from backend.app.core.config import settings
from backend.app.core.database import SessionLocal
from backend.app.models.models import User
from backend.app.services.ws_manager import ws_manager

router = APIRouter()


@router.websocket("/inbox")
async def inbox_websocket(websocket: WebSocket, token: str = ""):
    # Authenticate via JWT passed as query param
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email = payload.get("sub")
        if not email:
            raise JWTError()
    except JWTError:
        await websocket.close(code=4401)
        return

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email, User.is_active == True).first()  # noqa: E712
    finally:
        db.close()

    if not user:
        await websocket.close(code=4401)
        return

    clinic_id = user.clinic_id or 0
    await ws_manager.connect(websocket, clinic_id)
    try:
        while True:
            await websocket.receive_text()  # keepalive pings from client
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, clinic_id)
