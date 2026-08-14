"""Can a patient get through the manual form without being told how?

The first version failed on four counts, all of them silent. Cards that were
secretly links, so nothing said "chọn". A reload that landed at the top of the
page, so choosing a service looked like nothing happened and the calendar sat
below the fold. Fourteen identical day chips, so picking a day was guesswork
corrected one click later. And no step counter, so there was no way to know how
much was left.

None of those raise an error. They just cost the booking, which is the one thing
this page exists to produce — so they are worth asserting.
"""
import datetime
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api.endpoints.landing import _calendar_weeks, _slots_by_part
from backend.app.core.database import Base, get_db
from backend.app.main import app
from backend.app.models.models import (
    Branch, Clinic, Doctor, DoctorTimeOff, Service, WorkingSchedule,
)

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                       poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=engine)
    s = TestingSessionLocal()
    yield s
    s.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def clinic(db):
    """Two locations, so every step of the five-step form renders."""
    from backend.app.core.slug import assign_slug

    c = Clinic(name="Phòng khám CareDesk", is_active=True, landing_enabled=True)
    db.add(c)
    db.flush()
    assign_slug(db, c)

    branches = []
    for name in ("Quận 1", "Quận 10"):
        b = Branch(clinic_id=c.id, name=name, address=f"{name}, TP.HCM",
                   is_active=True, landing_enabled=True)
        db.add(b)
        db.flush()
        assign_slug(db, b)
        branches.append(b)

    service = Service(clinic_id=c.id, name="Trị mụn", price=500000, duration_minutes=30)
    doctor = Doctor(clinic_id=c.id, name="BS An", branch_id=branches[0].id, is_active=True)
    db.add_all([service, doctor])
    db.flush()
    for day in range(7):
        db.add(WorkingSchedule(doctor_id=doctor.id, branch_id=branches[0].id, day_of_week=day,
                               start_time=datetime.time(8, 0), end_time=datetime.time(17, 0)))
    db.commit()
    return {"clinic": c, "branches": branches, "service": service, "doctor": doctor}


def _url(clinic, **params):
    base = f"/book/{clinic['clinic'].slug}/dat-lich"
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{base}?{query}" if query else base


# --- the patient can tell what to click --------------------------------------

def test_every_option_carries_a_visible_select(client, clinic):
    """The original had none: a card that is silently a link reads as a
    description, and the patient waits for a button that never arrives."""
    step1 = client.get(_url(clinic)).text
    assert step1.count('class="card pick"') == 2, "thẻ cơ sở không phải nút chọn"
    assert step1.count(">Chọn<") >= 2, "không có chữ 'Chọn' trên thẻ cơ sở"

    step2 = client.get(_url(clinic, branch=clinic["branches"][0].slug)).text
    assert 'class="card pick"' in step2
    assert ">Chọn<" in step2, "không có chữ 'Chọn' trên thẻ dịch vụ"


def test_the_branch_button_does_not_promise_a_detail_page(client, clinic):
    """It said "Xem chi tiết" while actually selecting the branch. A button whose
    label describes a different action is worse than an unlabelled one."""
    step1 = client.get(_url(clinic)).text
    cards = re.findall(r'<a class="card pick".*?</a>', step1, re.S)
    assert cards
    for card in cards:
        assert "chi tiết" not in card.lower(), card


def test_choosing_something_jumps_to_the_next_question(client, clinic):
    """Without the fragment the reload lands at the top of the page and the next
    step is below the fold — which is exactly what "nothing happened" looks
    like."""
    step1 = client.get(_url(clinic)).text
    assert "#buoc-2" in step1, "chọn cơ sở xong không nhảy tới bước 2"

    step2 = client.get(_url(clinic, branch=clinic["branches"][0].slug)).text
    assert "#buoc-3" in step2, "chọn dịch vụ xong không nhảy tới bước 3"

    step3 = client.get(_url(clinic, branch=clinic["branches"][0].slug,
                            service=clinic["service"].id)).text
    assert "#buoc-4" in step3, "chọn ngày xong không nhảy tới bước 4"


def test_each_jump_target_exists_on_the_page_it_lands_on(client, clinic):
    """A fragment pointing at an id that is not there scrolls nowhere, which is
    indistinguishable from the bug it was meant to fix."""
    branch = clinic["branches"][0].slug
    landings = {
        "#buoc-2": _url(clinic, branch=branch),
        "#buoc-3": _url(clinic, branch=branch, service=clinic["service"].id),
    }
    for anchor, url in landings.items():
        assert f'id="{anchor[1:]}"' in client.get(url).text, f"{url} thiếu {anchor}"


def test_the_patient_is_told_where_they_are(client, clinic):
    step1 = client.get(_url(clinic)).text
    assert "Bước 1/5" in step1

    # One location means one question fewer, and the counter has to agree.
    solo = client.get(_url(clinic, branch=clinic["branches"][0].slug)).text
    assert "Bước 1/5" in solo and "Bước 2/5" in solo


# --- the day picker answers the question it is asked -------------------------

def test_the_calendar_says_which_days_can_be_booked(client, clinic):
    """The complaint was that fourteen identical chips make choosing a day
    guesswork. Real counts are the difference between a list and a choice."""
    page = client.get(_url(clinic, branch=clinic["branches"][0].slug,
                           service=clinic["service"].id)).text
    assert 'class="cal"' in page
    assert "chỗ" in page, "lịch không cho biết ngày nào còn chỗ"


def test_a_closed_day_is_shown_as_closed_not_offered(client, clinic, db):
    """Tết is the case that matters: a day the clinic is shut must not be
    clickable, or the patient finds out one click later — or at a locked door."""
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    # doctor_id NULL closes the whole clinic; no times means the whole day.
    db.add(DoctorTimeOff(clinic_id=clinic["clinic"].id, doctor_id=None,
                         start_date=tomorrow, end_date=tomorrow))
    db.commit()

    page = client.get(_url(clinic, branch=clinic["branches"][0].slug,
                           service=clinic["service"].id)).text
    closed = re.findall(r'<span class="cal-day off".*?</span>', page, re.S)
    assert closed, "ngày nghỉ vẫn hiện như ngày đặt được"
    assert f">{tomorrow.day}<" in "".join(closed), "ngày nghỉ không phải ngày đã khoá"

    # And it must not also be offered as a link somewhere on the same grid.
    bookable = re.findall(r'<a class="cal-day.*?</a>', page, re.S)
    assert not any(f"day={tomorrow.isoformat()}" in a for a in bookable)


def test_the_calendar_and_the_slot_list_never_disagree(client, clinic, db):
    """The grid is built by calling the same open_slots the next step uses. A
    second, faster implementation would drift from it within a release or two,
    and promise a Thursday that step 4 then refuses."""
    from backend.app.services.booking_flow import days_with_availability, open_slots

    today = datetime.date.today()
    grid = days_with_availability(db, clinic["clinic"].id, today, 5, 30,
                                  branch_id=clinic["branches"][0].id)
    for day, promised in grid:
        actual = len(open_slots(db, clinic["clinic"].id, day, 30,
                                branch_id=clinic["branches"][0].id))
        assert promised == actual, f"{day}: lịch hứa {promised}, thực tế {actual}"


def test_the_grid_lines_up_with_its_own_column_headings():
    """A calendar whose columns do not match the weekday names is worse than a
    list: it looks authoritative and is wrong."""
    start = datetime.date(2026, 8, 13)          # a Thursday, weekday() == 3
    weeks = _calendar_weeks([(start + datetime.timedelta(days=i), 1) for i in range(14)])

    assert weeks[0][:3] == [None, None, None], "đệm đầu tuần sai"
    for week in weeks:
        for column, cell in enumerate(week):
            if cell:
                assert cell[0].weekday() == column, f"{cell[0]} nằm sai cột"


# --- times are grouped the way patients think about them ---------------------

def test_times_are_split_into_parts_of_the_day():
    class Doc:
        name = "BS An"

    slots = [(datetime.time(h, 0), Doc()) for h in (9, 11, 14, 16, 19)]
    grouped = dict((name, len(items)) for name, items in _slots_by_part(slots))

    assert grouped == {"morning": 2, "afternoon": 2, "evening": 1}


def test_five_in_the_afternoon_is_not_evening():
    """chiều, not tối. Filing 17:00 under "buổi tối" makes the clinic look like
    it keeps hours it does not, and an after-work patient skips the group."""
    class Doc:
        name = "BS An"

    grouped = dict(_slots_by_part([(datetime.time(17, 0), Doc())]))
    assert "afternoon" in grouped and "evening" not in grouped


# --- nothing redundant on the page the patient is already on -----------------

def test_the_sticky_bar_does_not_link_to_the_current_page(client, clinic):
    """On the booking page it pointed at the booking page, costing 74px of every
    phone screen to do nothing."""
    page = client.get(_url(clinic)).text
    assert 'class="sticky-cta"' not in page

    brand = client.get(f"/book/{clinic['clinic'].slug}").text
    assert 'class="sticky-cta"' in brand, "thanh CTA phải còn ở trang giới thiệu"
