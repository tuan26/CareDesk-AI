"""
Inbound webhooks for external chat channels (Zalo OA, Facebook Messenger).
Each clinic exposes its own webhook URL: /api/v1/webhooks/{channel}/{clinic_id}.
Messages flow through the exact same AI pipeline as the web widget
(safety filter -> quota -> booking flow -> FAQ/LLM) and replies are pushed
back through the channel gateway (mock mode when tokens are not configured).
"""
from datetime import datetime
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from backend.app.core.database import get_db
from backend.app.models.models import Conversation, Message, PatientLead, Clinic
from backend.app.services.ai_engine import process_chat_message
from backend.app.services.patients import OPT_OUT_ACK, detects_opt_out, opt_out
from backend.app.services.channel_gateway import (
    get_integration, send_zalo_message, send_facebook_message
)
from backend.app.services.rate_limit import chat_rate_limiter
from backend.app.services.ws_manager import ws_manager
from backend.app.core import clock

router = APIRouter()


def _handle_inbound_message(db: Session, clinic_id: int, channel: str,
                            external_id: str, display_name: str, text: str) -> Conversation:
    """Map an external user to a PatientLead + Conversation and run the AI pipeline."""
    clinic = db.query(Clinic).filter(Clinic.id == clinic_id).first()
    if not clinic:
        raise HTTPException(status_code=404, detail="Clinic không tồn tại")

    lead = db.query(PatientLead).filter(
        PatientLead.clinic_id == clinic_id,
        PatientLead.external_id == external_id,
        PatientLead.source == channel
    ).first()
    if not lead:
        lead = PatientLead(
            clinic_id=clinic_id,
            full_name=display_name or f"Khách {channel.capitalize()} •{external_id[-4:]}",
            source=channel,
            external_id=external_id,
            consent_given=True,  # implied by messaging the OA/Page first
            consent_timestamp=clock.now()
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)

    conv = db.query(Conversation).filter(
        Conversation.patient_id == lead.id,
        Conversation.channel == channel
    ).order_by(Conversation.created_at.desc()).first()
    if not conv:
        conv = Conversation(clinic_id=clinic_id, patient_id=lead.id, channel=channel, status="bot_active")
        db.add(conv)
        db.commit()
        db.refresh(conv)

    # Save inbound patient message
    db.add(Message(conversation_id=conv.id, sender="patient", content=text))
    conv.updated_at = clock.now()
    db.commit()

    # "Dung nhan nua" has to take effect on the message that says it, not once a
    # human gets round to reading the inbox. Acknowledged and answered here,
    # because going silent on someone who asked you to stop reads as ignoring
    # them, and the next automated message would prove it.
    if detects_opt_out(text) and not lead.contact_opt_out:
        opt_out(db, lead, reason="patient_request")
        db.add(Message(conversation_id=conv.id, sender="bot", content=OPT_OUT_ACK))
        db.commit()
        if channel == "zalo":
            send_zalo_message(db, clinic_id, external_id, OPT_OUT_ACK)
        elif channel == "facebook":
            send_facebook_message(db, clinic_id, external_id, OPT_OUT_ACK)
        ws_manager.notify(clinic_id, {"type": "message", "conversation_id": conv.id,
                                      "sender": "patient"})
        return conv

    # AI reply only when the bot is active
    if conv.status == "bot_active":
        ai_response, is_handoff = process_chat_message(db, conv.id, text)
        if ai_response:
            if channel == "zalo":
                send_zalo_message(db, clinic_id, external_id, ai_response)
            elif channel == "facebook":
                send_facebook_message(db, clinic_id, external_id, ai_response)
        ws_manager.notify(clinic_id, {
            "type": "handoff" if is_handoff else "message",
            "conversation_id": conv.id, "sender": "bot"
        })
    else:
        ws_manager.notify(clinic_id, {"type": "message", "conversation_id": conv.id, "sender": "patient"})

    return conv


# --- ZALO OA ---
@router.get("/zalo/{clinic_id}")
def zalo_webhook_verify(clinic_id: int):
    """Zalo domain/webhook health check."""
    return {"status": "ok", "clinic_id": clinic_id}


@router.post("/zalo/{clinic_id}", dependencies=[Depends(chat_rate_limiter)])
async def zalo_webhook(clinic_id: int, request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    event_name = payload.get("event_name", "")

    if event_name == "user_send_text":
        sender_id = str(payload.get("sender", {}).get("id", ""))
        text = payload.get("message", {}).get("text", "")
        display_name = payload.get("sender", {}).get("name", "")
        if sender_id and text:
            _handle_inbound_message(db, clinic_id, "zalo", sender_id, display_name, text)

    return {"status": "received"}


# --- FACEBOOK MESSENGER ---
@router.get("/facebook/{clinic_id}")
def facebook_webhook_verify(
    clinic_id: int,
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
    db: Session = Depends(get_db)
):
    """Facebook webhook subscription verification (hub.challenge echo)."""
    integration = get_integration(db, clinic_id, "facebook")
    expected = integration.verify_token if integration else None
    if hub_mode == "subscribe" and expected and hub_verify_token == expected:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="Verify token không khớp")


@router.post("/facebook/{clinic_id}", dependencies=[Depends(chat_rate_limiter)])
async def facebook_webhook(clinic_id: int, request: Request, db: Session = Depends(get_db)):
    payload = await request.json()

    for entry in payload.get("entry", []):
        # Messenger inbox messages
        for event in entry.get("messaging", []):
            message = event.get("message", {})
            if message.get("is_echo"):
                continue  # skip our own outbound messages
            sender_id = str(event.get("sender", {}).get("id", ""))
            text = message.get("text", "")
            if sender_id and text:
                _handle_inbound_message(db, clinic_id, "facebook", sender_id, "", text)

        # Comment Guard: comments under the page's posts/ads
        for change in entry.get("changes", []):
            if change.get("field") != "feed":
                continue
            value = change.get("value", {})
            if value.get("item") != "comment" or value.get("verb") != "add":
                continue
            _handle_page_comment(db, clinic_id, value)

    return {"status": "received"}


def _handle_page_comment(db: Session, clinic_id: int, value: dict):
    """
    Comment Guard: auto-reply to ad comments ("giá bn?"), pull the person into
    Messenger via private reply, optionally hide the comment so competitors
    can't poach the lead. Config in facebook integration extra_config:
    {"comment_guard": true, "hide_comments": true, "comment_reply": "..."}
    """
    integration = get_integration(db, clinic_id, "facebook")
    cfg = (integration.extra_config or {}) if integration else {}
    if not cfg.get("comment_guard"):
        return

    comment_id = value.get("comment_id")
    commenter_id = str(value.get("from", {}).get("id", ""))
    comment_text = value.get("message", "")
    if not comment_id:
        return

    reply_text = cfg.get("comment_reply") or (
        "Dạ phòng khám đã nhận được câu hỏi của mình ạ! Em đã gửi thông tin chi tiết "
        "qua tin nhắn riêng, mình kiểm tra inbox giúp em nhé 💌"
    )

    token = integration.access_token if integration and integration.enabled else None
    if not token:
        print(f"[MOCK COMMENT GUARD] reply to comment {comment_id} ('{comment_text[:60]}') + private reply + hide")
    else:
        try:
            # 1. Public reply under the comment
            httpx.post(f"https://graph.facebook.com/v19.0/{comment_id}/comments",
                       params={"access_token": token}, json={"message": reply_text}, timeout=10)
            # 2. Private reply -> pulls the commenter into Messenger (then AI takes over)
            httpx.post("https://graph.facebook.com/v19.0/me/messages",
                       params={"access_token": token},
                       json={"recipient": {"comment_id": comment_id},
                             "message": {"text": "Chào bạn! Em là trợ lý của phòng khám. Bạn đang quan tâm dịch vụ nào để em tư vấn chi tiết ạ?"}},
                       timeout=10)
            # 3. Hide the comment from competitors (optional)
            if cfg.get("hide_comments"):
                httpx.post(f"https://graph.facebook.com/v19.0/{comment_id}",
                           params={"access_token": token}, json={"is_hidden": True}, timeout=10)
        except Exception as e:
            print(f"[COMMENT GUARD ERROR] {e}")

    # Log the lead signal so follow-up automation can fire even from a comment
    if commenter_id:
        from backend.app.services.events import emit_event
        lead = db.query(PatientLead).filter(
            PatientLead.clinic_id == clinic_id,
            PatientLead.external_id == commenter_id,
            PatientLead.source == "facebook"
        ).first()
        if not lead:
            lead = PatientLead(
                clinic_id=clinic_id, full_name=f"Khách FB comment •{commenter_id[-4:]}",
                source="facebook", external_id=commenter_id, consent_given=True,
                consent_timestamp=clock.now()
            )
            db.add(lead)
            db.flush()
        if any(kw in comment_text.lower() for kw in ("giá", "bao nhiêu", "phí", "bn")):
            emit_event(db, clinic_id, "price_asked", patient_id=lead.id,
                       payload={"service_name": "dịch vụ da liễu"})
        db.commit()
