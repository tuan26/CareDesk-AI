"""A nav link must land somewhere.

The nav is shared by all three public templates, but only the brand page carries
all four sections. "#bac-si" on the booking form was a link that pointed at an
id which existed on a different page, so clicking it did nothing at all — no
error, no navigation, nothing to report. Silent is the worst failure mode a link
has: nobody files a bug for a button that does not respond, they just leave.

So the rule this file enforces is blunt and mechanical: every href on a rendered
page that ends in "#something" either matches an id on that same page, or points
at another page entirely. Never at an id that is not there.
"""
import datetime
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.database import Base, get_db
from backend.app.main import app
from backend.app.models.models import (
    Branch, Clinic, Doctor, Service, WorkingSchedule,
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


def _build(db, branch_count: int):
    """A clinic with services, doctors and however many locations."""
    from backend.app.core.slug import assign_slug

    clinic = Clinic(name="Phòng khám CareDesk", is_active=True, landing_enabled=True)
    db.add(clinic)
    db.flush()
    assign_slug(db, clinic)

    branches = []
    for i in range(branch_count):
        b = Branch(clinic_id=clinic.id, name=f"Cơ sở {i + 1}", address=f"{i + 1} Lê Lợi",
                   is_active=True, landing_enabled=True)
        db.add(b)
        db.flush()
        assign_slug(db, b)
        branches.append(b)

    db.add(Service(clinic_id=clinic.id, name="Trị mụn", price=500000, duration_minutes=30))
    doctor = Doctor(clinic_id=clinic.id, name="BS An", branch_id=branches[0].id, is_active=True)
    db.add(doctor)
    db.flush()
    for day in range(7):
        db.add(WorkingSchedule(doctor_id=doctor.id, branch_id=branches[0].id, day_of_week=day,
                               start_time=datetime.time(8, 0), end_time=datetime.time(17, 0)))
    db.commit()
    return clinic, branches


def _anchors(html: str):
    """(same-page anchors, cross-page anchors) from the rendered markup."""
    hrefs = re.findall(r'href="([^"]*#[a-zA-Z0-9_-]+)"', html)
    return ([h[1:] for h in hrefs if h.startswith("#")],
            [h for h in hrefs if not h.startswith("#")])


def _ids(html: str):
    return set(re.findall(r'id="([a-zA-Z0-9_-]+)"', html))


def _assert_every_anchor_resolves(html: str, where: str):
    same_page, _ = _anchors(html)
    ids = _ids(html)
    missing = [a for a in same_page if a not in ids]
    assert not missing, f"{where}: neo trỏ tới id không tồn tại — {missing}"


@pytest.mark.parametrize("branch_count", [1, 3])
def test_every_in_page_anchor_has_a_target(client, db, branch_count):
    """The whole bug in one assertion, across all three templates.

    Parametrised on branch count because a single-location clinic renders no
    "other branches" section on its branch page — the nav must notice, or it
    offers a dead link to exactly the smallest customers.
    """
    clinic, branches = _build(db, branch_count)

    pages = {
        "trang thương hiệu": f"/book/{clinic.slug}",
        "trang cơ sở": f"/book/{clinic.slug}/{branches[0].slug}",
        "trang đặt lịch": f"/book/{clinic.slug}/dat-lich",
    }
    for where, path in pages.items():
        response = client.get(path)
        assert response.status_code == 200, f"{where} trả về {response.status_code}"
        _assert_every_anchor_resolves(response.text, where)


#: The marketing sections the shared nav points at. The booking form's own
#: "#buoc-N" step anchors are a different thing entirely and belong to the form.
SECTION_ANCHORS = ("dich-vu", "bac-si", "ket-qua", "co-so")


def test_the_booking_form_sends_section_links_home(client, db):
    """The booking form has no marketing sections at all, so every *nav* link on
    it has to be a trip back to the brand page rather than a no-op."""
    clinic, _ = _build(db, 2)

    html = client.get(f"/book/{clinic.slug}/dat-lich").text
    same_page, cross_page = _anchors(html)

    assert not [a for a in same_page if a in SECTION_ANCHORS], \
        f"trang đặt lịch không có section nào, nhưng có neo nội trang: {same_page}"

    section_links = [h for h in cross_page
                     if h.rsplit("#", 1)[-1] in SECTION_ANCHORS]
    assert any(h.endswith("#dich-vu") for h in section_links)
    assert all(h.startswith(f"/book/{clinic.slug}#") for h in section_links), section_links


def test_the_branch_page_scrolls_to_its_own_services(client, db):
    """Not a redirect to the brand page: the branch page's own service cards are
    pre-filled with this branch, and sending the visitor home would lose that."""
    clinic, branches = _build(db, 2)

    html = client.get(f"/book/{clinic.slug}/{branches[0].slug}").text
    same_page, cross_page = _anchors(html)

    assert "dich-vu" in same_page
    # No doctors section exists here, so that one link genuinely has to leave.
    assert any(h.endswith("#bac-si") for h in cross_page)
