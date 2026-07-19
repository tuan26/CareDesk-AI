"""
Outbound message gateway for external channels (Zalo OA, Facebook Messenger, ZNS, SMS).
Every sender degrades gracefully to a console mock when credentials are missing,
so the whole product remains demo-able without real accounts.
"""
import httpx
from typing import Optional
from sqlalchemy.orm import Session
from backend.app.core.config import settings
from backend.app.models.models import ChannelIntegration

ZALO_SEND_URL = "https://openapi.zalo.me/v3.0/oa/message/cs"
FB_SEND_URL = "https://graph.facebook.com/v19.0/me/messages"


def get_integration(db: Session, clinic_id: int, channel: str) -> Optional[ChannelIntegration]:
    return db.query(ChannelIntegration).filter(
        ChannelIntegration.clinic_id == clinic_id,
        ChannelIntegration.channel == channel
    ).first()


def send_zalo_message(db: Session, clinic_id: int, zalo_user_id: str, text: str) -> bool:
    integration = get_integration(db, clinic_id, "zalo")
    if not integration or not integration.enabled or not integration.access_token:
        print(f"[MOCK ZALO] -> user {zalo_user_id}: {text[:120]}")
        return True
    try:
        resp = httpx.post(
            ZALO_SEND_URL,
            headers={"access_token": integration.access_token, "Content-Type": "application/json"},
            json={"recipient": {"user_id": zalo_user_id}, "message": {"text": text}},
            timeout=10
        )
        ok = resp.status_code == 200 and resp.json().get("error", 0) == 0
        if not ok:
            print(f"[ZALO ERROR] {resp.text[:300]}")
        return ok
    except Exception as e:
        print(f"[ZALO ERROR] {e}")
        return False


def send_facebook_message(db: Session, clinic_id: int, psid: str, text: str) -> bool:
    integration = get_integration(db, clinic_id, "facebook")
    if not integration or not integration.enabled or not integration.access_token:
        print(f"[MOCK FACEBOOK] -> PSID {psid}: {text[:120]}")
        return True
    try:
        resp = httpx.post(
            FB_SEND_URL,
            params={"access_token": integration.access_token},
            json={
                "recipient": {"id": psid},
                "messaging_type": "RESPONSE",
                "message": {"text": text}
            },
            timeout=10
        )
        if resp.status_code != 200:
            print(f"[FACEBOOK ERROR] {resp.text[:300]}")
        return resp.status_code == 200
    except Exception as e:
        print(f"[FACEBOOK ERROR] {e}")
        return False


def send_zns_or_sms(db: Session, clinic_id: Optional[int], phone: str, text: str) -> str:
    """
    Send an appointment reminder to a phone number.
    Priority: Zalo ZNS (if clinic has Zalo integration) -> SMS gateway -> console mock.
    Returns the channel actually used.
    """
    if clinic_id:
        integration = get_integration(db, clinic_id, "zalo")
        if integration and integration.enabled and integration.access_token:
            # Real ZNS requires a pre-approved template; template id lives in extra_config.
            template_id = (integration.extra_config or {}).get("zns_template_id")
            if template_id:
                try:
                    resp = httpx.post(
                        "https://business.openapi.zalo.me/message/template",
                        headers={"access_token": integration.access_token, "Content-Type": "application/json"},
                        json={"phone": phone, "template_id": template_id, "template_data": {"content": text}},
                        timeout=10
                    )
                    if resp.status_code == 200 and resp.json().get("error", 0) == 0:
                        return "zns"
                    print(f"[ZNS ERROR] {resp.text[:300]}")
                except Exception as e:
                    print(f"[ZNS ERROR] {e}")

    if settings.SMS_API_KEY:
        # Plug your SMS provider here (eSMS, SpeedSMS, Twilio...). Left as a single point of integration.
        print(f"[SMS] -> {phone}: {text[:160]}")
        return "sms"

    print(f"[MOCK ZNS/SMS] -> {phone}: {text[:160]}")
    return "sms"


def reply_to_conversation_channel(db: Session, conversation, text: str):
    """
    Push a reply to whatever external channel a conversation lives on.
    Web conversations are pulled by the widget itself, so nothing to push.
    """
    if not text:
        return
    patient = conversation.patient
    if conversation.channel == "zalo" and patient and patient.external_id:
        send_zalo_message(db, conversation.clinic_id, patient.external_id, text)
    elif conversation.channel == "facebook" and patient and patient.external_id:
        send_facebook_message(db, conversation.clinic_id, patient.external_id, text)
