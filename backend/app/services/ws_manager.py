"""
WebSocket connection manager for the realtime staff inbox.
Sync endpoints (running in the threadpool) notify connected dashboards
through `notify()`, which schedules the broadcast on the main event loop.
"""
import asyncio
import json
from typing import Dict, Set, Optional
from fastapi import WebSocket


class WSManager:
    def __init__(self):
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.connections: Dict[int, Set[WebSocket]] = {}

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop

    async def connect(self, websocket: WebSocket, clinic_id: int):
        await websocket.accept()
        self.connections.setdefault(clinic_id or 0, set()).add(websocket)

    def disconnect(self, websocket: WebSocket, clinic_id: int):
        self.connections.get(clinic_id or 0, set()).discard(websocket)

    async def _broadcast(self, clinic_id: Optional[int], payload: dict):
        targets = set()
        if clinic_id is None:
            for conns in self.connections.values():
                targets |= conns
        else:
            targets = set(self.connections.get(clinic_id, set())) | set(self.connections.get(0, set()))
        message = json.dumps(payload)
        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:
                pass  # stale socket; cleanup happens on disconnect

    def notify(self, clinic_id: Optional[int], payload: dict):
        """Thread-safe fire-and-forget broadcast, callable from sync endpoints."""
        if not self.loop or not self.loop.is_running():
            return
        asyncio.run_coroutine_threadsafe(self._broadcast(clinic_id, payload), self.loop)


ws_manager = WSManager()
