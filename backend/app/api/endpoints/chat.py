from typing import Any, List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend.app.core.database import get_db
from backend.app.api.deps import verify_receptionist_or_above, verify_owner_or_admin
from backend.app.models.models import Conversation, Message, PatientLead, User
from backend.app.schemas.schemas import (
    ConversationOut, MessageOut, MessageBase, ConversationStatusUpdate, PatientLeadCreate
)
from backend.app.services.ai_engine import process_chat_message
from backend.app.services.evaluator import run_ai_evaluation

router = APIRouter()

@router.post("/conversations", response_model=ConversationOut)
def start_conversation(
    *,
    db: Session = Depends(get_db),
    lead_in: PatientLeadCreate
) -> Any:
    """
    Start a new conversation. Consent must be granted.
    """
    if not lead_in.consent_given:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bạn cần đồng ý với chính sách bảo mật thông tin để bắt đầu cuộc trò chuyện."
        )
        
    # Check if patient lead already exists by phone
    patient = None
    if lead_in.phone:
        patient = db.query(PatientLead).filter(PatientLead.phone == lead_in.phone).first()
        
    if not patient:
        patient = PatientLead(
            full_name=lead_in.full_name,
            phone=lead_in.phone,
            email=lead_in.email,
            source=lead_in.source,
            consent_given=True,
            consent_timestamp=datetime.utcnow()
        )
        db.add(patient)
        db.commit()
        db.refresh(patient)
    else:
        # Update consent
        patient.consent_given = True
        patient.consent_timestamp = datetime.utcnow()
        db.commit()

    # Create new conversation
    conv = Conversation(
        patient_id=patient.id,
        channel=lead_in.source,
        status="bot_active"
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    
    return conv


@router.post("/conversations/{conv_id}/messages", response_model=MessageOut)
def send_message(
    *,
    db: Session = Depends(get_db),
    conv_id: int,
    msg_in: MessageBase
) -> Any:
    """
    Patient sends a message to the bot. AI processes it and returns response.
    """
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Cuộc hội thoại không tồn tại")
        
    # Save patient message
    patient_msg = Message(
        conversation_id=conv.id,
        sender="patient",
        content=msg_in.content
    )
    db.add(patient_msg)
    db.commit()
    db.refresh(patient_msg)

    # Process via AI Engine
    ai_response, is_handoff = process_chat_message(db, conv.id, msg_in.content)
    
    # Query the last message created (which would be the bot's response)
    bot_msg = db.query(Message).filter(
        Message.conversation_id == conv.id,
        Message.sender == "bot"
    ).order_by(Message.created_at.desc()).first()
    
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
    """
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Cuộc hội thoại không tồn tại")
        
    # Save agent message
    agent_msg = Message(
        conversation_id=conv.id,
        sender="agent",
        content=msg_in.content
    )
    db.add(agent_msg)
    
    # Touch updated timestamp
    conv.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(agent_msg)
    
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
    query = db.query(Conversation)
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
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Cuộc hội thoại không tồn tại")
    
    # Load messages
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
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Cuộc hội thoại không tồn tại")
        
    conv.status = status_in.status
    db.commit()
    db.refresh(conv)
    return conv


@router.delete("/conversations/{conv_id}/data-erasure", status_code=status.HTTP_204_NO_CONTENT)
def erase_patient_data(
    conv_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
):
    """
    Delete patient conversation data upon request (GDPR compliance / Data Erasure).
    """
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Cuộc hội thoại không tồn tại")
        
    patient = conv.patient
    
    # Delete conversation (this cascade deletes all associated Messages)
    db.delete(conv)
    db.commit()
    
    # Delete patient lead if they don't have other conversations/appointments
    if patient:
        other_convs = db.query(Conversation).filter(Conversation.patient_id == patient.id).count()
        appts = db.query(PatientLead).filter(PatientLead.id == patient.id).first().appointments
        
        if other_convs == 0 and len(appts) == 0:
            db.delete(patient)
            db.commit()
            
    return


@router.post("/evaluate-ai")
def evaluate_ai_quality(
    db: Session = Depends(get_db),
    current_user: User = Depends(verify_owner_or_admin)
) -> Any:
    """
    Run automated AI evaluation against Golden Dataset.
    """
    report = run_ai_evaluation(db)
    return report
