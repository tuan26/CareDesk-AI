import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.app.core.database import Base
from backend.app.models.models import PatientLead, Conversation, Message, Appointment

engine = create_engine("sqlite:///:memory:")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)


def test_data_erasure_cascade(db_session):
    # 1. Create Patient
    patient = PatientLead(full_name="Bệnh nhân A", phone="0901112222", consent_given=True)
    db_session.add(patient)
    db_session.commit()
    
    # 2. Create Conversation
    conv = Conversation(patient_id=patient.id, channel="web", status="bot_active")
    db_session.add(conv)
    db_session.commit()
    
    # 3. Create Messages
    msg1 = Message(conversation_id=conv.id, sender="patient", content="Xin chào")
    msg2 = Message(conversation_id=conv.id, sender="bot", content="Chào bạn, tôi giúp gì được ạ?")
    db_session.add_all([msg1, msg2])
    db_session.commit()
    
    # Verify they exist
    assert db_session.query(PatientLead).count() == 1
    assert db_session.query(Conversation).count() == 1
    assert db_session.query(Message).count() == 2
    
    # 4. Perform erasure logic: delete conversation
    db_session.delete(conv)
    db_session.commit()
    
    # Verify Messages are deleted due to cascade ondelete="CASCADE"
    assert db_session.query(Message).count() == 0
    assert db_session.query(Conversation).count() == 0
    
    # Check if we should delete patient too (no appointments or other conversations)
    other_convs = db_session.query(Conversation).filter(Conversation.patient_id == patient.id).count()
    appts = db_session.query(Appointment).filter(Appointment.patient_id == patient.id).count()
    
    if other_convs == 0 and appts == 0:
        db_session.delete(patient)
        db_session.commit()
        
    assert db_session.query(PatientLead).count() == 0
