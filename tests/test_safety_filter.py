import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.app.core.database import Base
from backend.app.models.models import AISafetyRule, Conversation, PatientLead, Message
from backend.app.services.ai_engine import check_safety_rules, process_chat_message

# Setup in-memory SQLite database for testing
engine = create_engine("sqlite:///:memory:")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    
    # Seed required safety rules
    rules = [
        AISafetyRule(
            category="urgent",
            keyword_pattern="đau dữ dội,khó thở,sưng mặt dữ dội,chảy máu nhiều",
            fallback_message="Cảnh báo: Tình trạng khẩn cấp, đang chuyển lễ tân gấp.",
            force_handoff=True
        ),
        AISafetyRule(
            category="clinical_diagnosis",
            keyword_pattern="bệnh gì,kê đơn,uống thuốc gì",
            fallback_message="Từ chối chẩn đoán/kê đơn, chuyển bác sĩ tư vấn.",
            force_handoff=True
        )
    ]
    db.add_all(rules)
    db.commit()
    
    yield db
    
    db.close()
    Base.metadata.drop_all(bind=engine)


def test_safety_check_matched(db_session):
    # Test case 1: Urgent safety keywords matching
    rule = check_safety_rules(db_session, "Mặt tôi bị sưng mặt dữ dội và chảy máu nhiều")
    assert rule is not None
    assert rule.category == "urgent"
    assert rule.force_handoff is True

    # Test case 2: Clinical diagnosis keywords matching
    rule2 = check_safety_rules(db_session, "Kê đơn giúp tôi hoặc chỉ tôi uống thuốc gì")
    assert rule2 is not None
    assert rule2.category == "clinical_diagnosis"


def test_safety_check_unmatched(db_session):
    # Test case 3: Safe message
    rule = check_safety_rules(db_session, "Tôi muốn đặt lịch khám da liễu")
    assert rule is None


def test_handoff_triggering(db_session):
    # Setup dummy lead and conversation
    lead = PatientLead(full_name="Nguyễn Văn A", phone="0901234567", consent_given=True)
    db_session.add(lead)
    db_session.commit()
    
    conv = Conversation(patient_id=lead.id, channel="web", status="bot_active")
    db_session.add(conv)
    db_session.commit()

    # Process dangerous message
    res, is_handoff = process_chat_message(db_session, conv.id, "Mắt tôi bị sưng mặt dữ dội và chảy máu nhiều!")
    
    # Check if handoff was triggered
    assert is_handoff is True
    
    # Refresh conversation state
    db_session.refresh(conv)
    assert conv.status == "handoff_requested"
    
    # Check that fallback message was saved
    last_msg = db_session.query(Message).filter(Message.conversation_id == conv.id).order_by(Message.created_at.desc()).first()
    assert last_msg.sender == "bot"
    assert "Cảnh báo" in last_msg.content
