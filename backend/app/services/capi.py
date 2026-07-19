"""
Facebook Conversions API (CAPI): feed booking/deposit events back to Meta so
ad campaigns optimize for real bookings instead of vague messages.
Config lives per-clinic in the facebook ChannelIntegration.extra_config:
{"pixel_id": "...", "capi_token": "..."}. Mock-logs when unconfigured.
"""
import hashlib
import time
import httpx
from typing import Optional
from sqlalchemy.orm import Session
from backend.app.services.channel_gateway import get_integration


def send_capi_event(db: Session, clinic_id: Optional[int], event_name: str,
                    phone: Optional[str] = None, value: float = 0.0, external_id: Optional[str] = None):
    """event_name: 'Schedule' (booked) | 'Purchase' (deposit/package paid)."""
    if not clinic_id:
        return
    integration = get_integration(db, clinic_id, "facebook")
    cfg = (integration.extra_config or {}) if integration else {}
    pixel_id, token = cfg.get("pixel_id"), cfg.get("capi_token")

    user_data = {}
    if phone:
        normalized = "84" + phone.lstrip("0")
        user_data["ph"] = [hashlib.sha256(normalized.encode()).hexdigest()]
    if external_id:
        user_data["external_id"] = [hashlib.sha256(str(external_id).encode()).hexdigest()]

    if not pixel_id or not token:
        print(f"[MOCK CAPI] clinic {clinic_id}: {event_name} value={value:,.0f}")
        return

    try:
        resp = httpx.post(
            f"https://graph.facebook.com/v19.0/{pixel_id}/events",
            params={"access_token": token},
            json={"data": [{
                "event_name": event_name,
                "event_time": int(time.time()),
                "action_source": "chat",
                "user_data": user_data,
                "custom_data": {"currency": "VND", "value": value}
            }]},
            timeout=10
        )
        if resp.status_code != 200:
            print(f"[CAPI ERROR] {resp.text[:300]}")
    except Exception as e:
        print(f"[CAPI ERROR] {e}")
