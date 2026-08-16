from typing import Any, List, Optional
from datetime import timedelta
from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.orm import Session
from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.api.deps import verify_receptionist_or_above, verify_owner
from backend.app.models.models import Conversation, Message, PatientLead, User, Clinic, Branch
from backend.app.schemas.schemas import (
    ConversationOut, MessageOut, MessageBase, ConversationStatusUpdate, PatientLeadCreate
)
from backend.app.services.ai_engine import process_chat_message
from backend.app.services.evaluator import run_ai_evaluation
from backend.app.services.audit import log_action
from backend.app.services.rate_limit import chat_rate_limiter
from backend.app.services.ws_manager import ws_manager
from backend.app.services.channel_gateway import reply_to_conversation_channel
from backend.app.services.public_chat_session import (
    issue_public_chat_session, verify_and_rotate_public_chat_session,
)
from backend.app.core import clock
from backend.app.core.handoff import assistant_may_reply
from backend.app.services.i18n import ui_text
from backend.app.services.patients import upsert_lead

router = APIRouter()


def _scoped_conv(query, user: User):
    if user.clinic_id:
        return query.filter(Conversation.clinic_id == user.clinic_id)
    return query


def _authorize_public_conversation(db: Session, conv: Conversation, session_token: Optional[str],
                                   rotate: bool = False) -> Optional[str]:
    """Validate and rotate the conversation-bound session.

    Always required. This used to be opt-in per clinic, defaulting to off, which
    meant GET /chat/conversations/31/messages returned a stranger's medical
    conversation to anyone who counted upwards — no token, no login. Every
    client already keeps the token issued when the conversation starts (the
    corner panel, the /chat page and the embeddable widget all send it back), so
    there was nothing on the other side of that trade.
    """
    valid, rotated_token = verify_and_rotate_public_chat_session(
        db, conv.id, session_token, rotate=rotate)
    if not valid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Phiên trò chuyện không hợp lệ hoặc đã hết hạn.")
    return rotated_token



@router.post("/conversations", response_model=ConversationOut, dependencies=[Depends(chat_rate_limiter)])
def start_conversation(
    *,
    db: Session = Depends(get_db),
    lead_in: PatientLeadCreate
) -> Any:
    """
    Start a new conversation from the web widget. Consent must be granted.
    Multi-tenant: the widget passes clinic_id; defaults to the first clinic.
    """
    if not lead_in.consent_given:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Bạn cần đồng ý với chính sách bảo mật thông tin để bắt đầu cuộc trò chuyện."
        )

    clinic_id = lead_in.clinic_id
    if not clinic_id:
        clinics = db.query(Clinic).limit(2).all()
        clinic_id = clinics[0].id if len(clinics) == 1 else None
    clinic = db.query(Clinic).filter(Clinic.id == clinic_id, Clinic.is_active == True).first() if clinic_id else None  # noqa: E712
    if not clinic:
        raise HTTPException(status_code=404, detail="Không tìm thấy phòng khám hoạt động cho cuộc trò chuyện.")
    locale = lead_in.locale if lead_in.locale in {"vi", "ja", "en"} else clinic.default_locale


    # Referral tracking: resolve the friend's code to the referring patient.
    # Only meaningful for someone new — an existing patient already has a source.
    referred_by = None
    if lead_in.referral_code_used:
        referrer = db.query(PatientLead).filter(
            PatientLead.clinic_id == clinic_id,
            PatientLead.referral_code == lead_in.referral_code_used.strip().upper()
        ).first()
        referred_by = referrer.id if referrer else None

    # One record per phone, and the name they just gave wins over the one stored
    # from a previous visit. See services/patients.py.
    patient = upsert_lead(
        db, clinic_id, full_name=lead_in.full_name, phone=lead_in.phone,
        source=lead_in.source, email=lead_in.email,
        referred_by_patient_id=referred_by,
    )
    db.commit()
    db.refresh(patient)

    # Pin the location the patient arrived from, so the booking flow proposes
    # slots at that branch instead of the first doctor it happens to find.
    branch_id = None
    if lead_in.branch_id:
        branch = db.query(Branch).filter(
            Branch.id == lead_in.branch_id,
            Branch.clinic_id == clinic_id,      # never accept another tenant's branch
            Branch.is_active == True,           # noqa: E712
        ).first()
        branch_id = branch.id if branch else None

        # Create new conversation
    conv = Conversation(
        clinic_id=clinic_id,
        branch_id=branch_id,
        patient_id=patient.id,
        channel=lead_in.source,
        status="bot_active",
        locale=locale,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)

    # The greeting is part of the transcript, not decoration. Every client drew
    # it locally and none stored it, so reception's inbox opened on the
    # patient's first question with no idea what they had been greeted with —
    # and resuming a thread lost it entirely.
    db.add(Message(conversation_id=conv.id, sender="bot",
                   content=ui_text(locale, "welcome", name=patient.full_name or "")))

    ws_manager.notify(clinic_id, {"type": "conversation_started", "conversation_id": conv.id})
    # Optional field: legacy clients ignore it, V1 widgets retain and rotate it.
    conv.public_session_token = issue_public_chat_session(db, conv.id)
    db.commit()
    return conv


@router.post("/conversations/{conv_id}/messages", response_model=MessageOut, dependencies=[Depends(chat_rate_limiter)])
def send_message(
    *,
    response: Response,
    db: Session = Depends(get_db),
    conv_id: int,
    msg_in: MessageBase,
    x_caredesk_session: Optional[str] = Header(default=None)
) -> Any:
    """
    Patient sends a message. If the bot is active, the AI processes and replies.
        After handoff, the message is stored for the human agent (no bot reply).
    """
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()

    if not conv:
        raise HTTPException(status_code=404, detail="Cuộc hội thoại không tồn tại")

    rotated = _authorize_public_conversation(db, conv, x_caredesk_session, rotate=True)
    if rotated:
        response.headers["X-CareDesk-Session"] = rotated

    # Save patient message
    patient_msg = Message(
        conversation_id=conv.id,
        sender="patient",
        content=msg_in.content
    )
    db.add(patient_msg)
    conv.updated_at = clock.now()
    db.commit()
    db.refresh(patient_msg)

    # A receptionist typing, or a handoff the assistant must not talk over:
    # store, alert staff, say nothing.
    #
    # "Waiting for a human" is not the same as "a human is here". Treating them
    # alike meant every message sent while the queue was unattended — nights,
    # weekends — got no reply at all. Patients asked answerable questions twice
    # into silence and left. See core/handoff.py.
    if not assistant_may_reply(conv.status, conv.handoff_reason):
        ws_manager.notify(conv.clinic_id, {"type": "message", "conversation_id": conv.id, "sender": "patient"})
        return patient_msg

    # Process via AI Engine
    ai_response, is_handoff = process_chat_message(db, conv.id, msg_in.content)
    ws_manager.notify(conv.clinic_id, {
        "type": "handoff" if is_handoff else "message",
        "conversation_id": conv.id,
        "sender": "bot"
    })

    # Query the last bot message created (the AI's reply).
    # Order by id: created_at only has second precision, ties would return a stale reply.
    bot_msg = db.query(Message).filter(
        Message.conversation_id == conv.id,
        Message.sender == "bot"
    ).order_by(Message.id.desc()).first()

    if not bot_msg:
        # Fallback if somehow process_chat_message did not save (should not happen)
        bot_msg = Message(
            conversation_id=conv.id,
            sender="bot",
            content=ai_response
        )
        db.add(bot_msg)
        db.commit()
        db.refresh(bot_msg)

    return bot_msg


@router.get("/conversations/{conv_id}/resume", dependencies=[Depends(chat_rate_limiter)])
def resume_conversation(
    response: Response,
    conv_id: int,
    db: Session = Depends(get_db),
    x_caredesk_session: Optional[str] = Header(default=None)
) -> Any:
    """Pick a conversation back up where the patient left it.

    Reopening the panel used to start from nothing: the consent form again, the
    greeting again, and an assistant with no idea what had just been discussed.

    Continuity is keyed on the token this browser holds, not on the phone number
    typed into the form. A phone number is not a secret — it is printed on
    receipts and shared in group chats — and resuming on one would let anyone
    who knows a number read that person's medical conversation. The browser that
    had the conversation is the one that gets it back.

    Threads older than the cutoff are not resumed. A fortnight-old exchange is
    not context, it is clutter, and its half-finished booking refers to dates
    that have since passed.
    """
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Cuộc hội thoại không tồn tại")

    kept = _authorize_public_conversation(db, conv, x_caredesk_session)
    if kept:
        response.headers["X-CareDesk-Session"] = kept

    age = clock.now() - (conv.updated_at or conv.created_at or clock.now())
    if age > timedelta(hours=settings.PUBLIC_CHAT_RESUME_MAX_AGE_HOURS):
        raise HTTPException(status_code=status.HTTP_410_GONE,
                            detail="Cuộc trò chuyện đã quá cũ để tiếp tục.")

    # A booking half-collected days ago points at a date that has passed. Keep
    # the conversation, drop the stale intent, so the patient is not answered
    # with "ngày bạn chọn đã qua mất rồi" for a day they never re-chose.
    state = dict(conv.booking_state or {})
    if state.get("date") and state["date"] < clock.today().isoformat():
        for key in ("date", "slot", "proposed_slots"):
            state.pop(key, None)
        conv.booking_state = state
        db.commit()

    messages = db.query(Message).filter(
        Message.conversation_id == conv.id,
        Message.sender != "system",
    ).order_by(Message.id.asc()).all()
    return {
        "conversation_id": conv.id,
        "status": conv.status,
        "messages": [MessageOut.model_validate(m, from_attributes=True) for m in messages],
    }


@router.get("/conversations/{conv_id}/messages", response_model=List[MessageOut], dependencies=[Depends(chat_rate_limiter)])
def poll_messages(
    response: Response,
    conv_id: int,
    after_id: int = 0,
    db: Session = Depends(get_db),
    x_caredesk_session: Optional[str] = Header(default=None)
) -> Any:
    """
    Public polling endpoint for the chat widget: fetch messages newer than `after_id`
        so patients can see human agent replies after a handoff.
    """
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()

    if not conv:
        raise HTTPException(status_code=404, detail="Cuộc hội thoại không tồn tại")

    # Polling does not rotate: it fires every four seconds and racing a slow
    # send is what used to strand the browser on a token the server had already
    # replaced. See public_chat_session.
    kept = _authorize_public_conversation(db, conv, x_caredesk_session)
    if kept:
        response.headers["X-CareDesk-Session"] = kept
    return db.query(Message).filter(
        Message.conversation_id == conv_id,
        Message.id > after_id
    ).order_by(Message.created_at.asc()).all()


@router.post("/conversations/{conv_id}/agent-messages", response_model=MessageOut)
def send_agent_message(
    *,
    db: Session = Depends(get_db),
    conv_id: int,
    msg_in: MessageBase,
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    """
    Agent sends a message in a conversation. AI does not respond.
    The reply is also pushed to the external channel (Zalo/Facebook) when applicable.
    """
    conv = _scoped_conv(db.query(Conversation), current_user).filter(Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Cuộc hội thoại không tồn tại")

    agent_msg = Message(
        conversation_id=conv.id,
        sender="agent",
        content=msg_in.content
    )
    db.add(agent_msg)
    conv.updated_at = clock.now()
    db.commit()
    db.refresh(agent_msg)

    # Push to Zalo/Facebook if this conversation lives on an external channel
    reply_to_conversation_channel(db, conv, msg_in.content)
    ws_manager.notify(conv.clinic_id, {"type": "message", "conversation_id": conv.id, "sender": "agent"})

    return agent_msg


@router.get("/conversations", response_model=List[ConversationOut])
def list_conversations(
    db: Session = Depends(get_db),
    status: Optional[str] = None,
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    """
    List conversations for receptionist inbox.
    """
    query = _scoped_conv(db.query(Conversation), current_user)
    if status:
        query = query.filter(Conversation.status == status)
    return query.order_by(Conversation.updated_at.desc()).all()


@router.get("/conversations/{conv_id}", response_model=ConversationOut)
def get_conversation_detail(
    conv_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    """
    Get conversation details and messages for admin dashboard inbox.
    """
    conv = _scoped_conv(db.query(Conversation), current_user).filter(Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Cuộc hội thoại không tồn tại")

    messages = db.query(Message).filter(Message.conversation_id == conv_id).order_by(Message.created_at.asc()).all()
    conv.messages = messages
    return conv


@router.put("/conversations/{conv_id}/status", response_model=ConversationOut)
def update_conversation_status(
    conv_id: int,
    status_in: ConversationStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_receptionist_or_above)
) -> Any:
    """
    Change conversation status (e.g. receptionist taking over -> agent_active).
    """
    conv = _scoped_conv(db.query(Conversation), current_user).filter(Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Cuộc hội thoại không tồn tại")

    conv.status = status_in.status
    log_action(db, current_user.id, "update_conversation_status", f"Hội thoại #{conv.id} -> {status_in.status}")
    db.commit()
    db.refresh(conv)
    ws_manager.notify(conv.clinic_id, {"type": "status", "conversation_id": conv.id, "status": conv.status})
    return conv


@router.delete("/conversations/{conv_id}/data-erasure", status_code=status.HTTP_204_NO_CONTENT)
def erase_patient_data(
    conv_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner)
):
    """
    Delete patient conversation data upon request (GDPR compliance / Data Erasure).
    """
    conv = _scoped_conv(db.query(Conversation), current_user).filter(Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Cuộc hội thoại không tồn tại")

    patient = conv.patient
    log_action(db, current_user.id, "data_erasure", f"Xóa dữ liệu hội thoại #{conv.id}")

    # Delete conversation (this cascade deletes all associated Messages)
    db.delete(conv)
    db.commit()

    # Delete patient lead if they don't have other conversations/appointments
    if patient:
        other_convs = db.query(Conversation).filter(Conversation.patient_id == patient.id).count()
        appts = patient.appointments

        if other_convs == 0 and len(appts) == 0:
            db.delete(patient)
            db.commit()

    return


@router.post("/evaluate-ai")
def evaluate_ai_quality(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner)
) -> Any:
    """
    Run automated AI evaluation against Golden Dataset.
    """
    report = run_ai_evaluation(db)
    return report
