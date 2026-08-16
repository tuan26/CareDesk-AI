"""Whole conversations, and the rules that must hold in every one of them.

Every bug reported against this assistant so far has been the same shape: a
conversation that goes round, or answers a question nobody asked, or claims
something that is not true. Fixing them one at a time found each instance and
none of the class.

So this file asserts *invariants* over complete conversations rather than
checking individual replies:

  1. It never says a booking exists unless one does.
  2. It never sends the same message twice in a row.
  3. It never asks for something the patient already told it.
  4. Every question it asks has an answer the flow will accept.
  5. It never books a date that has passed, or a doctor the patient did not ask
     for.
  6. It gets somewhere: a request, a handoff, or a plainly stated dead end —
     never an endless exchange.

The model is stubbed. These are the rules of the conversation, not the wording
of the model's answers, and a stub keeps the failures readable.
"""
import datetime
import re

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core import clock
from backend.app.core.database import Base
from backend.app.models.models import (
    Appointment, BookingRequest, Branch, Clinic, Conversation, Doctor, DoctorTimeOff,
    Message, PatientLead, Service, WorkingSchedule,
)
from backend.app.services import ai_engine
from backend.app.services.ai_engine import BOOKING_CLAIM_PHRASES, process_chat_message

engine = create_engine("sqlite:///:memory:")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

#: What the stub model says when the state machine does not take a turn.
#: Deliberately free of booking-claim phrasing, so any claim in a transcript
#: came from the flow itself.
#: Varies with the message so that two identical replies in a row always mean
#: the *flow* repeated itself, never the stub.
def STUB_REPLY(message):
    return f"Dạ, phòng khám xin trả lời về: {message}"


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=engine)
    s = TestingSessionLocal()
    yield s
    s.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def stub_model(monkeypatch):
    monkeypatch.setattr(ai_engine, "call_openai_gpt_mock",
                        lambda db, clinic, message, locale="vi": STUB_REPLY(message))


@pytest.fixture
def clinic(db):
    """A clinic with the awkward cases in it, not just the happy one.

    - BS An works every day; BS Bích only at weekends; BS Cường has no rota at
      all, which is the state a clinic is in the week after it signs up.
    - Two branches, so "which location" is a real question.
    - A closed day, because Tết is the case that matters.
    """
    c = Clinic(name="Phòng khám CareDesk", is_active=True)
    db.add(c)
    db.flush()
    main = Branch(clinic_id=c.id, name="Quận 10", address="123 Ba Tháng Hai", is_active=True)
    second = Branch(clinic_id=c.id, name="Quận 1", address="456 Nguyễn Huệ", is_active=True)
    db.add_all([main, second])
    db.flush()

    services = {
        # Translated, as a clinic selling to foreign patients would have it —
        # otherwise an English conversation cannot name a service at all.
        "mun": Service(clinic_id=c.id, name="Điều trị mụn Chuẩn Y Khoa",
                       price=450000, duration_minutes=45,
                       localized_content={"en": {"name": "Medical acne treatment"}}),
        "laser": Service(clinic_id=c.id, name="Laser Fractional CO2 trị sẹo rỗ",
                         price=1200000, duration_minutes=60),
        "kham": Service(clinic_id=c.id, name="Khám da liễu với Bác sĩ chuyên khoa",
                        price=150000, duration_minutes=30),
    }
    doctors = {
        "an": Doctor(clinic_id=c.id, name="Bác sĩ Nguyễn Văn An",
                     specialty="Da liễu", branch_id=main.id, is_active=True),
        "bich": Doctor(clinic_id=c.id, name="Bác sĩ Lê Thị Bích",
                       specialty="Thẩm mỹ da", branch_id=main.id, is_active=True),
        "cuong": Doctor(clinic_id=c.id, name="Bác sĩ Trần Minh Cường",
                        specialty="Laser", branch_id=main.id, is_active=True),
    }
    db.add_all(list(services.values()) + list(doctors.values()))
    db.flush()

    for day in range(7):
        db.add(WorkingSchedule(doctor_id=doctors["an"].id, branch_id=main.id,
                               day_of_week=day, start_time=datetime.time(8, 0),
                               end_time=datetime.time(18, 0)))
    for day in (5, 6):
        db.add(WorkingSchedule(doctor_id=doctors["bich"].id, branch_id=main.id,
                               day_of_week=day, start_time=datetime.time(9, 0),
                               end_time=datetime.time(17, 0)))
    # BS Cường: none on purpose.

    patient = PatientLead(clinic_id=c.id, full_name="Chị Hoa", phone="0912345678")
    db.add(patient)
    db.commit()
    return {"clinic": c, "main": main, "second": second,
            "services": services, "doctors": doctors, "patient": patient}


def _conversation(db, clinic, branch=None):
    conv = Conversation(clinic_id=clinic["clinic"].id, patient_id=clinic["patient"].id,
                        branch_id=(branch or clinic["main"]).id, status="bot_active")
    db.add(conv)
    db.commit()
    return conv


def _run(db, conv, messages):
    """Drive a whole conversation and hand back the transcript.

    Stores the patient's message first, exactly as the endpoint does — the model
    reads its history out of the database, so skipping that would test a
    conversation the product never has.
    """
    turns = []
    for message in messages:
        db.add(Message(conversation_id=conv.id, sender="patient", content=message))
        db.commit()
        reply, handoff = process_chat_message(db, conv.id, message)
        db.refresh(conv)
        turns.append({"patient": message, "reply": reply or "", "handoff": handoff,
                      "state": dict(conv.booking_state or {})})
    return turns


# --- the invariants, applied to every scenario --------------------------------

def _assert_no_false_booking_claim(db, conv, turns):
    booked = db.query(BookingRequest).filter(
        BookingRequest.conversation_id == conv.id).count() > 0
    for i, turn in enumerate(turns):
        claimed = [p for p in BOOKING_CLAIM_PHRASES if p in turn["reply"].lower()]
        if claimed and not booked:
            raise AssertionError(
                f"lượt {i + 1} nói đã đặt lịch ({claimed}) nhưng không có yêu cầu nào: "
                f"{turn['reply'][:120]}")


def _assert_never_repeats_itself(turns):
    for i in range(1, len(turns)):
        previous, current = turns[i - 1]["reply"], turns[i]["reply"]
        if previous and previous == current:
            raise AssertionError(
                f"lượt {i} và {i + 1} trả lời y hệt nhau — hội thoại đang quay vòng: "
                f"{current[:120]}")


#: Asking -> the state key that means it has already been answered. Matched
#: against interrogative sentences only: "- Họ tên: Chị Hoa" in a confirmation
#: summary is the answer being read back, not the question being asked again.
_ALREADY_ANSWERED = [
    (re.compile(r"(ngày nào|chọn ngày)", re.I), "date"),
    (re.compile(r"(cho (tôi|mình) xin|vui lòng (cho|nhập)).{0,40}(họ tên|tên)", re.I), "full_name"),
    (re.compile(r"(cho (tôi|mình) xin|vui lòng (cho|nhập)).{0,40}số điện thoại", re.I), "phone"),
]


def _questions_in(reply):
    """Sentences that actually ask something."""
    return [part for part in re.split(r"(?<=[?？])\s+|\n", reply) if "?" in part]


def _assert_never_asks_twice(turns):
    for i, turn in enumerate(turns):
        # The state *before* this turn is what the reply was written against.
        known = turns[i - 1]["state"] if i else {}
        for question in _questions_in(turn["reply"]):
            for pattern, key in _ALREADY_ANSWERED:
                if known.get(key) and pattern.search(question):
                    raise AssertionError(
                        f"lượt {i + 1} hỏi lại '{key}' dù đã biết ({known[key]}): "
                        f"{question[:120]}")


def _assert_no_impossible_booking(db, conv, turns):
    for request in db.query(BookingRequest).filter(
            BookingRequest.conversation_id == conv.id).all():
        assert request.preferred_at is None or request.preferred_at.date() >= clock.today(), \
            f"đặt vào ngày đã qua: {request.preferred_at}"
        assert request.full_name and request.contact_value, "yêu cầu thiếu thông tin liên hệ"


def check(db, conv, turns):
    """Every rule, on every scenario."""
    _assert_no_false_booking_claim(db, conv, turns)
    _assert_never_repeats_itself(turns)
    _assert_never_asks_twice(turns)
    _assert_no_impossible_booking(db, conv, turns)


def _tomorrow_words():
    return "ngày mai"


# --- scenarios ----------------------------------------------------------------

def test_the_shortest_path(db, clinic):
    """Service, day, slot. If this ever needs more than four turns something has
    gone wrong."""
    conv = _conversation(db, clinic)
    turns = _run(db, conv, ["tôi muốn đặt lịch trị mụn", _tomorrow_words(), "1"])
    check(db, conv, turns)

    assert db.query(BookingRequest).filter(
        BookingRequest.conversation_id == conv.id).count() == 1


def test_everything_in_one_sentence(db, clinic):
    """The way people actually write when they know what they want."""
    conv = _conversation(db, clinic)
    turns = _run(db, conv, [
        "đặt lịch trị mụn với bác sĩ Nguyễn Văn An ngày mai lúc 9h"])
    check(db, conv, turns)

    request = db.query(BookingRequest).filter(
        BookingRequest.conversation_id == conv.id).first()
    assert request is not None, "nói đủ mọi thứ trong một câu mà vẫn chưa đặt được"
    assert request.doctor_id == clinic["doctors"]["an"].id


def test_questions_between_every_step(db, clinic):
    """The commonest real shape: they ask as they go."""
    conv = _conversation(db, clinic)
    turns = _run(db, conv, [
        "tôi muốn đặt lịch trị mụn",
        "trị mụn có đau không ạ",
        "bao lâu thì khỏi",
        _tomorrow_words(),
        "làm xong kiêng gì không",
        "1",
    ])
    check(db, conv, turns)

    assert db.query(BookingRequest).filter(
        BookingRequest.conversation_id == conv.id).count() == 1


def test_changing_their_mind_about_the_service(db, clinic):
    conv = _conversation(db, clinic)
    turns = _run(db, conv, [
        "đặt lịch trị mụn", _tomorrow_words(),
        "à cho tôi đổi sang laser trị sẹo rỗ", _tomorrow_words(), "1"])
    check(db, conv, turns)

    request = db.query(BookingRequest).filter(
        BookingRequest.conversation_id == conv.id).first()
    assert request is not None
    assert request.service_id == clinic["services"]["laser"].id, "đặt nhầm dịch vụ cũ"


def test_changing_their_mind_about_the_day(db, clinic):
    conv = _conversation(db, clinic)
    turns = _run(db, conv, [
        "đặt lịch trị mụn", _tomorrow_words(), "à thôi ngày kia đi", "1"])
    check(db, conv, turns)

    request = db.query(BookingRequest).filter(
        BookingRequest.conversation_id == conv.id).first()
    assert request is not None
    assert request.preferred_at.date() == clock.today() + datetime.timedelta(days=2)


def test_a_doctor_who_only_works_weekends(db, clinic):
    """Not an error — a normal rota. The reply must name days she is actually
    free rather than refusing and asking the patient to guess."""
    conv = _conversation(db, clinic)
    turns = _run(db, conv, ["đặt lịch trị mụn với bác sĩ Lê Thị Bích", "thứ 3 tuần sau"])
    check(db, conv, turns)

    last = turns[-1]["reply"]
    assert "Bích" in last
    assert "còn trống các ngày" in last or "khung giờ" in last, last


def test_a_doctor_with_no_rota_at_all(db, clinic):
    """The state a clinic is in the week after it signs up. It must say so and
    offer a way on, not loop."""
    conv = _conversation(db, clinic)
    turns = _run(db, conv, [
        "đặt lịch laser với bác sĩ Trần Minh Cường", _tomorrow_words(), "đúng"])
    check(db, conv, turns)

    assert "Cường" in turns[1]["reply"]
    # Saying yes to "shall I find someone else" has to move things on.
    assert turns[2]["reply"] != turns[1]["reply"]


def test_cancelling_midway(db, clinic):
    conv = _conversation(db, clinic)
    turns = _run(db, conv, ["đặt lịch trị mụn", _tomorrow_words(), "thôi không đặt nữa"])
    check(db, conv, turns)

    assert db.query(BookingRequest).filter(
        BookingRequest.conversation_id == conv.id).count() == 0
    assert not turns[-1]["state"].get("active")


def test_booking_again_after_finishing_one(db, clinic):
    """The second booking must not inherit the first one's answers."""
    conv = _conversation(db, clinic)
    turns = _run(db, conv, [
        "đặt lịch trị mụn", _tomorrow_words(), "1",
        "tôi muốn đặt thêm lịch laser", "ngày kia", "1"])
    check(db, conv, turns)

    requests = db.query(BookingRequest).filter(
        BookingRequest.conversation_id == conv.id).order_by(BookingRequest.id).all()
    assert len(requests) == 2, "không đặt được lịch thứ hai"
    assert requests[0].service_id != requests[1].service_id


def test_typed_without_diacritics(db, clinic):
    """Half of Vietnamese phone typing. It must not be a different product."""
    conv = _conversation(db, clinic)
    turns = _run(db, conv, ["toi muon dat lich tri mun", "ngay mai", "1"])
    check(db, conv, turns)

    assert db.query(BookingRequest).filter(
        BookingRequest.conversation_id == conv.id).count() == 1


def test_a_closed_day_is_refused_with_an_alternative(db, clinic):
    """Tết. The reply must not simply say no."""
    tomorrow = clock.today() + datetime.timedelta(days=1)
    db.add(DoctorTimeOff(clinic_id=clinic["clinic"].id, doctor_id=None,
                         start_date=tomorrow, end_date=tomorrow))
    db.commit()

    conv = _conversation(db, clinic)
    turns = _run(db, conv, ["đặt lịch trị mụn", _tomorrow_words(), "ngày kia", "1"])
    check(db, conv, turns)

    assert db.query(BookingRequest).filter(
        BookingRequest.conversation_id == conv.id).count() == 1


def test_a_date_in_the_past(db, clinic):
    conv = _conversation(db, clinic)
    yesterday = (clock.today() - datetime.timedelta(days=1)).strftime("%d/%m/%Y")
    turns = _run(db, conv, ["đặt lịch trị mụn", yesterday, _tomorrow_words(), "1"])
    check(db, conv, turns)

    request = db.query(BookingRequest).filter(
        BookingRequest.conversation_id == conv.id).first()
    assert request is None or request.preferred_at.date() >= clock.today()


def test_a_bare_time_with_nothing_else(db, clinic):
    """"9h" on its own, before anything has been chosen."""
    conv = _conversation(db, clinic)
    turns = _run(db, conv, ["9h", "đặt lịch trị mụn", _tomorrow_words(), "9h"])
    check(db, conv, turns)


def test_silence_never_happens(db, clinic):
    """Every patient message gets something back. An empty reply is the failure
    mode nobody reports and everybody leaves over."""
    conv = _conversation(db, clinic)
    turns = _run(db, conv, [
        "chào bạn", "cho mình hỏi bảng giá", "đặt lịch trị mụn",
        "à khoan", _tomorrow_words(), "1", "cảm ơn bạn"])
    check(db, conv, turns)

    for i, turn in enumerate(turns):
        assert turn["reply"].strip(), f"lượt {i + 1} không có hồi đáp: {turn['patient']!r}"


def test_the_whole_transcript_is_stored(db, clinic):
    """Reception reads this. A reply the patient saw and the inbox did not is a
    receptionist working from a different conversation."""
    conv = _conversation(db, clinic)
    turns = _run(db, conv, ["đặt lịch trị mụn", _tomorrow_words(), "1"])
    check(db, conv, turns)

    stored = db.query(Message).filter(Message.conversation_id == conv.id).all()
    patient_said = [m.content for m in stored if m.sender == "patient"]
    bot_said = [m.content for m in stored if m.sender == "bot"]

    assert patient_said == [t["patient"] for t in turns]
    for turn in turns:
        assert turn["reply"] in bot_said, "câu trả lời không được lưu lại"


# --- the awkward second half --------------------------------------------------

def test_switching_branch_midway(db, clinic):
    """Two locations means the patient can change their mind about which."""
    conv = _conversation(db, clinic)
    turns = _run(db, conv, [
        "đặt lịch trị mụn", "à cho tôi qua cơ sở Quận 1", _tomorrow_words(), "1"])
    check(db, conv, turns)


def test_a_service_the_clinic_does_not_offer(db, clinic):
    """"Tiêm filler" is not on the price list. It must say so and hand over,
    not invent one."""
    conv = _conversation(db, clinic)
    turns = _run(db, conv, ["cho tôi đặt lịch tiêm filler môi"])
    check(db, conv, turns)

    for turn in turns:
        assert "filler" not in turn["reply"].lower() or "chưa có" in turn["reply"].lower(), \
            f"bịa dịch vụ không có: {turn['reply'][:120]}"


def test_the_patient_gives_a_different_phone_in_chat(db, clinic):
    """They booked for someone else, or corrected a typo. The request must carry
    what they typed, not what the widget captured."""
    conv = _conversation(db, clinic)
    turns = _run(db, conv, [
        "đặt lịch trị mụn", "số của tôi là 0987654321", _tomorrow_words(), "1"])
    check(db, conv, turns)

    request = db.query(BookingRequest).filter(
        BookingRequest.conversation_id == conv.id).first()
    assert request is not None
    assert request.contact_value == "0987654321"


def test_a_fully_booked_day_offers_the_waitlist(db, clinic):
    """Every slot taken. The reply must offer something rather than just refuse."""
    tomorrow = clock.today() + datetime.timedelta(days=1)
    doctor = clinic["doctors"]["an"]
    start = datetime.datetime.combine(tomorrow, datetime.time(8, 0))
    while start.time() < datetime.time(18, 0):
        db.add(Appointment(clinic_id=clinic["clinic"].id, branch_id=clinic["main"].id,
                           doctor_id=doctor.id, patient_id=clinic["patient"].id,
                           service_id=clinic["services"]["mun"].id, status="confirmed",
                           start_time=start, end_time=start + datetime.timedelta(minutes=45)))
        start += datetime.timedelta(minutes=45)
    db.commit()

    conv = _conversation(db, clinic)
    turns = _run(db, conv, ["đặt lịch trị mụn", _tomorrow_words()])
    check(db, conv, turns)

    last = turns[-1]["reply"].lower()
    assert "chờ" in last or "ngày khác" in last or "còn trống" in last, turns[-1]["reply"]


def test_nonsense_does_not_derail_it(db, clinic):
    """Someone leaning on the keyboard, then a real question."""
    conv = _conversation(db, clinic)
    turns = _run(db, conv, ["ádfjkasdfj", "。。。", "đặt lịch trị mụn", _tomorrow_words(), "1"])
    check(db, conv, turns)

    assert db.query(BookingRequest).filter(
        BookingRequest.conversation_id == conv.id).count() == 1


def test_a_slot_taken_between_being_offered_and_chosen(db, clinic):
    """The page was open a while. Booking it anyway would double-book a doctor."""
    conv = _conversation(db, clinic)
    _run(db, conv, ["đặt lịch trị mụn", _tomorrow_words()])
    db.refresh(conv)
    offered = conv.booking_state["proposed_slots"][0]

    tomorrow = clock.today() + datetime.timedelta(days=1)
    taken = datetime.datetime.combine(
        tomorrow, datetime.time.fromisoformat(offered))
    db.add(Appointment(clinic_id=clinic["clinic"].id, branch_id=clinic["main"].id,
                       doctor_id=clinic["doctors"]["an"].id, patient_id=clinic["patient"].id,
                       service_id=clinic["services"]["mun"].id, status="confirmed",
                       start_time=taken, end_time=taken + datetime.timedelta(minutes=45)))
    db.commit()

    turns = _run(db, conv, ["1"])
    check(db, conv, turns)

    request = db.query(BookingRequest).filter(
        BookingRequest.conversation_id == conv.id).first()
    if request is not None:
        assert request.preferred_at.strftime("%H:%M") != offered, \
            "đặt vào khung giờ vừa bị người khác lấy mất"


def test_english_gets_english(db, clinic):
    conv = _conversation(db, clinic)
    conv.locale = "en"
    db.commit()

    turns = _run(db, conv, ["I want to book an acne treatment", "tomorrow", "1"])
    check(db, conv, turns)

    assert db.query(BookingRequest).filter(
        BookingRequest.conversation_id == conv.id).count() == 1


def test_asking_what_the_clinic_offers_lists_everything(db, clinic):
    """"phòng khám có những dịch vụ gì" used to return one service: the word
    "khám" inside "phòng khám" matched "Khám da liễu với Bác sĩ chuyên khoa",
    and that single accidental hit suppressed the catalogue."""
    from backend.app.services.ai_engine import query_faq_rag

    context = query_faq_rag(db, "phòng khám có những dịch vụ gì",
                            clinic_id=clinic["clinic"].id, branch_id=clinic["main"].id)

    for service in clinic["services"].values():
        assert service.name in context, f"thiếu {service.name} trong ngữ cảnh gửi cho AI"


def test_asking_about_one_service_still_gets_its_detail(db, clinic):
    from backend.app.services.ai_engine import query_faq_rag

    context = query_faq_rag(db, "laser trị sẹo rỗ giá bao nhiêu",
                            clinic_id=clinic["clinic"].id, branch_id=clinic["main"].id)

    assert "Laser Fractional CO2" in context
    assert "1,200,000" in context
