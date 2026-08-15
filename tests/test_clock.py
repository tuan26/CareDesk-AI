"""One clock, or the product quietly lies about time.

Two were running. `server_default=func.now()` is CURRENT_TIMESTAMP, which both
SQLite and Postgres give in UTC; everything the application wrote used the
machine clock. Seven hours apart, in the same column.

The visible symptom was an inbox showing messages seven hours old the moment
they arrived. The expensive one was invisible: every "hôm nay" report built its
range from the local clock and filtered a UTC column, so it dropped this
morning's work and counted last night's twice.

And on a production box — which runs UTC, not Hanoi — the machine clock is wrong
for every clinic this is sold to. Hence an explicit clinic timezone rather than
whatever the server happens to be set to.
"""
import datetime
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core import clock
from backend.app.core.database import Base
from backend.app.models.models import Clinic, Conversation, Message, PatientLead

engine = create_engine("sqlite:///:memory:")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=engine)
    s = TestingSessionLocal()
    yield s
    s.close()
    Base.metadata.drop_all(bind=engine)


def test_the_clock_is_the_clinic_not_the_server():
    """Production runs UTC. A reminder scheduled off the server clock would go
    out at three in the morning, which is the kind of thing a clinic switches
    the product off for."""
    expected = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=7)

    assert abs((clock.now() - expected.replace(tzinfo=None)).total_seconds()) < 5


def test_the_clock_is_naive():
    """The whole product compares against naive values — working hours, slot
    times, date.today(). An aware datetime on one side of those raises
    TypeError, so this is load-bearing rather than a style choice."""
    assert clock.now().tzinfo is None
    assert isinstance(clock.today(), datetime.date)


def test_today_is_today_at_the_clinic():
    """At 18:00 UTC it is already tomorrow in Hanoi. A server using its own date
    would offer slots on a day that has passed."""
    assert clock.today() == clock.now().date()


def test_stored_rows_use_the_same_clock_as_the_application(db):
    """The bug itself: a row written by the database default sat seven hours
    behind one written by the application, in the same table."""
    clinic = Clinic(name="CareDesk", is_active=True)
    db.add(clinic)
    db.flush()
    patient = PatientLead(clinic_id=clinic.id, full_name="Chị Hoa", phone="0901234567")
    db.add(patient)
    db.flush()
    conv = Conversation(clinic_id=clinic.id, patient_id=patient.id)
    db.add(conv)
    db.flush()
    db.add(Message(conversation_id=conv.id, sender="patient", content="xin chào"))
    db.commit()

    message = db.query(Message).first()
    drift = abs((message.created_at - clock.now()).total_seconds())

    assert drift < 60, f"mốc thời gian lệch {drift / 3600:.1f} giờ so với đồng hồ ứng dụng"


def test_a_reports_range_actually_covers_stored_rows(db):
    """What the mismatch really cost: the range is built from the clinic clock
    and the column was filled by the database. If they disagree, today's work is
    missing from today's report."""
    clinic = Clinic(name="CareDesk", is_active=True)
    db.add(clinic)
    db.flush()
    db.add(PatientLead(clinic_id=clinic.id, full_name="Anh Nam", phone="0900000000"))
    db.commit()

    start = datetime.datetime.combine(clock.today(), datetime.time.min)
    end = datetime.datetime.combine(clock.today(), datetime.time.max)
    found = db.query(PatientLead).filter(
        PatientLead.created_at >= start, PatientLead.created_at <= end).count()

    assert found == 1, "khách tạo hôm nay không nằm trong khoảng 'hôm nay'"


def test_no_backend_code_reaches_for_the_machine_clock():
    """A single datetime.now() reintroduces the split the moment it runs on a
    UTC server — and it would look correct on a laptop in Hanoi, which is how it
    got here in the first place."""
    # JWT "exp" is defined in UTC seconds by the spec, and the public chat
    # session writes and compares its own aware-UTC pair — neither touches a
    # clinic-time column, so both keep their own clock on purpose.
    allowed = {"app/core/security.py", "app/services/public_chat_session.py"}

    offenders = []
    root = Path(clock.__file__).resolve().parents[2]      # backend/
    for path in root.rglob("*.py"):
        relative = path.relative_to(root).as_posix()
        if path.name == "clock.py" or relative in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in (r"\bdatetime\.now\(\)", r"\bdate\.today\(\)", r"\bdatetime\.utcnow\(\)"):
            if re.search(pattern, text):
                offenders.append(f"{relative}: {pattern}")

    assert not offenders, "dùng đồng hồ máy thay vì clock.now(): " + ", ".join(offenders)
