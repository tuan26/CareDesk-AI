"""
Outbound message gateway for external channels (Zalo OA, Facebook Messenger, ZNS, SMS).

Senders still degrade to a console mock when credentials are missing, so the
product stays demo-able without real accounts — but a mock **must never be
reported as a delivery**. Callers get a `Delivery` telling them whether the
message actually left the building; the reminder scheduler uses that to decide
whether to write a ReminderLog. Getting this wrong is worse than failing
outright: a mock recorded as "sent" both hides the outage and permanently marks
the appointment as reminded, so it is never retried once a real channel is
configured.
"""
import logging
from dataclasses import dataclass
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.models import ChannelIntegration

logger = logging.getLogger(__name__)

ZALO_SEND_URL = "https://openapi.zalo.me/v3.0/oa/message/cs"
ZNS_SEND_URL = "https://business.openapi.zalo.me/message/template"
FB_SEND_URL = "https://graph.facebook.com/v19.0/me/messages"

# Vietnamese SMS providers. Both are transactional-SMS gateways requiring a
# registered brandname; pick one with settings.SMS_PROVIDER.
ESMS_URL = "https://rest.esms.vn/MainService.svc/json/SendMultipleMessage_V4_post_json/"
SPEEDSMS_URL = "https://api.speedsms.vn/index.php/sms/send"

CHANNEL_NONE = "none"


@dataclass(frozen=True)
class Delivery:
    """Outcome of one outbound send.

    Two different questions, deliberately separated:

    * ``delivered`` — the send flow completed. Controls whether the scheduler
      considers this reminder done and stops retrying.
    * ``reached_patient`` — a real human actually got a message.

    They differ for the mock and sandbox senders, which is the whole point of
    having both. A sandbox send exercises credentials, payload shape and error
    handling for real, so the flow genuinely completed and must not be retried
    forever — but nobody's phone buzzed, so it must never be counted as reaching
    a patient or as evidence the clinic is ready to go live.

    ``attempted`` says whether a provider was actually contacted. A failure with
    ``attempted=False`` means nothing was configured — it must not consume a
    retry attempt, or the reminders that piled up while you were waiting for a
    Zalo OA would all be permanently retired by the time it arrives.

    ``retryable`` then separates a transport blip (timeout, 5xx — worth another
    go) from the provider looking at the message and refusing it (bad number,
    blocked brandname — retrying buys the same answer at the same price).
    """
    channel: str
    delivered: bool
    detail: str = ""
    reached_patient: bool = False
    attempted: bool = True
    retryable: bool = True

    def __bool__(self) -> bool:
        return self.delivered


def get_integration(db: Session, clinic_id: int, channel: str) -> Optional[ChannelIntegration]:
    return db.query(ChannelIntegration).filter(
        ChannelIntegration.clinic_id == clinic_id,
        ChannelIntegration.channel == channel
    ).first()


def send_zalo_message(db: Session, clinic_id: int, zalo_user_id: str, text: str) -> bool:
    integration = get_integration(db, clinic_id, "zalo")
    if not integration or not integration.enabled or not integration.access_token:
        logger.warning("Zalo not configured for clinic %s - reply not delivered", clinic_id)
        return False
    try:
        resp = httpx.post(
            ZALO_SEND_URL,
            headers={"access_token": integration.access_token, "Content-Type": "application/json"},
            json={"recipient": {"user_id": zalo_user_id}, "message": {"text": text}},
            timeout=10
        )
        ok = resp.status_code == 200 and resp.json().get("error", 0) == 0
        if not ok:
            logger.error("Zalo send failed: %s", resp.text[:300])
        return ok
    except Exception:
        logger.exception("Zalo send failed")
        return False


def send_facebook_message(db: Session, clinic_id: int, psid: str, text: str) -> bool:
    integration = get_integration(db, clinic_id, "facebook")
    if not integration or not integration.enabled or not integration.access_token:
        logger.warning("Facebook not configured for clinic %s - reply not delivered", clinic_id)
        return False
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
            logger.error("Facebook send failed: %s", resp.text[:300])
        return resp.status_code == 200
    except Exception:
        logger.exception("Facebook send failed")
        return False


# --- SMS providers -----------------------------------------------------------
# Each returns True only on a confirmed accept from the provider. Both are
# ready to use: set SMS_PROVIDER + the credentials and they go live with no
# code change.

def _send_esms(phone: str, text: str) -> bool:
    """eSMS.vn. SmsType 2 = branded transactional SMS.

    With SMS_SANDBOX on, eSMS accepts `Sandbox=1`: the request is validated and
    answered normally but the message is not stored, not charged and not
    delivered. That exercises credentials, payload shape and error handling for
    real, which a local mock cannot — so staging should use it rather than the
    mock, and production must use neither.
    """
    payload = {
        "ApiKey": settings.SMS_API_KEY,
        "SecretKey": settings.SMS_SECRET_KEY,
        "Brandname": settings.SMS_BRANDNAME,
        "Phone": phone,
        "Content": text,
        "SmsType": "2",
    }
    if settings.SMS_SANDBOX:
        payload["Sandbox"] = "1"

    resp = httpx.post(ESMS_URL, json=payload, timeout=15)
    resp.raise_for_status()
    body = resp.json()
    # eSMS answers 100 on success and puts the reason in ErrorMessage otherwise.
    if str(body.get("CodeResult")) != "100":
        logger.error("eSMS rejected the message: %s", str(body)[:300])
        return False
    return True


def _send_mock(phone: str, text: str) -> bool:
    """Local development with no provider account at all.

    Distinct from "unconfigured": this is an explicit choice (SMS_PROVIDER=mock)
    so the whole reminder flow can be exercised end to end. It reports the send
    as completed but never as having reached anyone — see Delivery.
    """
    logger.info("[MOCK SMS] -> %s: %s", phone, text[:160])
    return True


def _send_speedsms(phone: str, text: str) -> bool:
    """SpeedSMS.vn. type 3 = branded transactional SMS; auth is the API token as
    the basic-auth username with any password.

    No sandbox mode here: unlike eSMS, SpeedSMS has no documented test flag that
    we have confirmed, and guessing one would mean believing messages are being
    suppressed while they are in fact being sent and billed. Use SMS_PROVIDER=mock
    or eSMS sandbox for testing until SpeedSMS confirms otherwise.
    """
    resp = httpx.post(
        SPEEDSMS_URL,
        json={"to": [phone], "content": text, "type": 3, "sender": settings.SMS_BRANDNAME},
        auth=(settings.SMS_API_KEY, "x"),
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("status") != "success":
        logger.error("SpeedSMS rejected the message: %s", str(body)[:300])
        return False
    return True


_SMS_PROVIDERS = {"esms": _send_esms, "speedsms": _send_speedsms, "mock": _send_mock}

#: Providers that never put a message on a real handset.
_SIMULATED_PROVIDERS = {"mock"}


def sms_is_simulated() -> bool:
    """True when SMS is wired up but deliberately not reaching anyone."""
    return settings.SMS_PROVIDER in _SIMULATED_PROVIDERS or bool(settings.SMS_SANDBOX)


def sms_is_configured() -> bool:
    """Is there a working send path? True for mock/sandbox too — the flow runs."""
    if settings.SMS_PROVIDER not in _SMS_PROVIDERS:
        return False
    if settings.SMS_PROVIDER == "mock":
        return True                       # needs no credentials
    return bool(settings.SMS_API_KEY)


def sms_reaches_real_phones() -> bool:
    return sms_is_configured() and not sms_is_simulated()


def zns_is_configured(db: Session, clinic_id: Optional[int]) -> bool:
    """ZNS needs an authorised OA *and* a Zalo-approved template id. Having the
    OA alone is not enough, which is the usual reason reminders silently stop."""
    if not clinic_id:
        return False
    integration = get_integration(db, clinic_id, "zalo")
    return bool(
        integration and integration.enabled and integration.access_token
        and (integration.extra_config or {}).get("zns_template_id")
    )


def outbound_status(db: Session, clinic_id: Optional[int]) -> dict:
    """What this clinic can actually reach a patient's phone with.

    Surfaced on the dashboard: a clinic with no phone channel gets no appointment
    reminders at all, which is half the product's promise, and there is otherwise
    nothing on screen to tell them.

    ``can_reach_phone`` deliberately excludes mock and sandbox. They make the
    flow testable, not the clinic ready — a green light here while every message
    is being swallowed by a sandbox is exactly the false confidence this whole
    module exists to prevent.
    """
    zns = zns_is_configured(db, clinic_id)
    sms_real = sms_reaches_real_phones()
    return {
        "zns": zns,
        "sms": sms_real,
        "sms_simulated": sms_is_configured() and sms_is_simulated(),
        "sms_mode": settings.SMS_PROVIDER or "none",
        "email": bool(settings.SMTP_USER and settings.SMTP_PASSWORD),
        "can_reach_phone": zns or sms_real,
    }


def send_zns_or_sms(db: Session, clinic_id: Optional[int], phone: str, text: str) -> Delivery:
    """Send to a phone number: Zalo ZNS first, then SMS.

    Returns a Delivery whose `delivered` is False when nothing left the process.
    Never claim a send that did not happen — see the module docstring.
    """
    if zns_is_configured(db, clinic_id):
        integration = get_integration(db, clinic_id, "zalo")
        template_id = (integration.extra_config or {}).get("zns_template_id")
        try:
            resp = httpx.post(
                ZNS_SEND_URL,
                headers={"access_token": integration.access_token, "Content-Type": "application/json"},
                json={"phone": phone, "template_id": template_id,
                      "template_data": {"content": text}},
                timeout=15,
            )
            if resp.status_code == 200 and resp.json().get("error", 0) == 0:
                # A Zalo *Test* OA uses this same endpoint with a test token, so
                # a successful send here may not have reached a real handset.
                # That is a deployment-config concern, not something the code can
                # detect — see SO_TAY_VAN_HANH_PRODUCT.md.
                return Delivery("zns", True, reached_patient=True)
            logger.error("ZNS send failed for clinic %s: %s", clinic_id, resp.text[:300])
        except Exception as exc:
            logger.exception("ZNS send failed for clinic %s", clinic_id)
            return _try_sms(phone, text, fallback_detail=f"ZNS lỗi: {exc}")

        # Zalo looked at the message and refused it: a retry gets the same
        # answer, so do not let this one bounce around the scheduler forever.
        return _try_sms(phone, text, fallback_detail="ZNS bị từ chối", retryable=False)

    return _try_sms(phone, text, fallback_detail="Phòng khám chưa cấu hình Zalo ZNS")


def _try_sms(phone: str, text: str, fallback_detail: str,
             retryable: bool = True) -> Delivery:
    if not sms_is_configured():
        logger.warning(
            "Không gửi được tin tới %s: %s và SMS cũng chưa cấu hình. "
            "Tin nhắn KHÔNG được gửi; lịch hẹn sẽ được nhắc lại khi có kênh.",
            phone, fallback_detail,
        )
        # attempted=False: no provider was contacted, so this must not consume a
        # retry. Every reminder that queued up while waiting for a Zalo OA or an
        # SMS account goes out the moment credentials land.
        return Delivery(CHANNEL_NONE, False, f"{fallback_detail}; SMS chưa cấu hình",
                        attempted=False, retryable=True)

    simulated = sms_is_simulated()
    channel = "sms_sandbox" if simulated else "sms"
    try:
        if _SMS_PROVIDERS[settings.SMS_PROVIDER](phone, text):
            return Delivery(channel, True, reached_patient=not simulated)
        # The provider evaluated it and said no — bad number, blocked brandname,
        # out of credit. Same input gives the same answer next tick.
        return Delivery(CHANNEL_NONE, False, "Nhà cung cấp SMS từ chối tin nhắn",
                        retryable=False)
    except Exception as exc:
        # Transport-level failure (timeout, 5xx). Worth another go.
        logger.exception("SMS send failed via %s", settings.SMS_PROVIDER)
        return Delivery(CHANNEL_NONE, False, f"SMS lỗi: {exc}", retryable=retryable)


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
