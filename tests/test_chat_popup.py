"""The assistant opens where the visitor already is.

A separate chat page costs the thing they were reading. They were half way down
the price list and the question was *about that* — a full-page navigation throws
it away and replaces it with an empty form, so the question arrives without its
context or does not arrive at all.

Two properties are worth locking down, because both fail silently:

  * the launcher stays a real link, so a blocked or broken script still reaches
    the clinic rather than leaving a dead button on the page;
  * the copy blob stays valid JSON with its placeholders intact, because the
    panel parses it at load and a bad parse means no chat at all, on every page.
"""
import datetime
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api.endpoints.landing import _chat_copy
from backend.app.core.database import Base, get_db
from backend.app.main import app
from backend.app.models.models import Branch, Clinic, Doctor, Service, WorkingSchedule
from backend.app.services.i18n import SUPPORTED_LOCALES

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
    from backend.app.core.slug import assign_slug

    c = Clinic(name="Phòng khám CareDesk", is_active=True, landing_enabled=True)
    db.add(c)
    db.flush()
    assign_slug(db, c)
    branch = Branch(clinic_id=c.id, name="Quận 1", address="1 Lê Lợi",
                    is_active=True, landing_enabled=True)
    db.add(branch)
    db.flush()
    assign_slug(db, branch)
    db.add(Service(clinic_id=c.id, name="Trị mụn", price=500000, duration_minutes=30))
    doctor = Doctor(clinic_id=c.id, name="BS An", branch_id=branch.id, is_active=True)
    db.add(doctor)
    db.flush()
    for day in range(7):
        db.add(WorkingSchedule(doctor_id=doctor.id, branch_id=branch.id, day_of_week=day,
                               start_time=datetime.time(8, 0), end_time=datetime.time(17, 0)))
    db.commit()
    return {"clinic": c, "branch": branch}


def _pages(clinic):
    slug = clinic["clinic"].slug
    return {
        "trang thương hiệu": f"/book/{slug}",
        "trang cơ sở": f"/book/{slug}/{clinic['branch'].slug}",
        "trang đặt lịch": f"/book/{slug}/dat-lich",
    }


def test_the_panel_is_on_every_public_page(client, clinic):
    """Including the booking form: someone stuck on step 3 is exactly who needs
    to ask a question without losing the three steps they have filled in."""
    for where, path in _pages(clinic).items():
        html = client.get(path).text
        assert 'id="cd-launcher"' in html, f"{where}: thiếu nút mở chat"
        assert 'id="cd-panel"' in html, f"{where}: thiếu khung chat"
        assert 'id="cd-copy"' in html, f"{where}: thiếu bản dịch cho khung chat"


def test_the_launcher_is_still_a_real_link(client, clinic):
    """Progressive enhancement, not decoration. If the script never runs, these
    have to go somewhere — a button that silently does nothing is worse than no
    button, because nobody reports it."""
    html = client.get(f"/book/{clinic['clinic'].slug}").text

    import re
    opens = re.findall(r'<a[^>]*data-cd-open[^>]*>', html)
    assert opens, "không có liên kết nào mở khung chat"
    for tag in opens:
        href = re.search(r'href="([^"]+)"', tag)
        assert href and "/chat/" in href.group(1), f"liên kết không có đích thật: {tag}"


def test_the_panel_is_not_a_section(client, clinic):
    """The page gives every <section> 76px of padding and a rule underneath. A
    floating panel wearing that inherits a white band above its own header —
    which is exactly what it looked like the first time."""
    html = client.get(f"/book/{clinic['clinic'].slug}").text
    assert '<section id="cd-panel"' not in html


@pytest.mark.parametrize("locale", sorted(SUPPORTED_LOCALES))
def test_the_copy_blob_survives_the_trip(locale):
    """It is parsed by the browser at load, so a malformed blob costs the chat on
    every page at once."""
    data = json.loads(_chat_copy(locale).replace("<\\/", "</"))

    assert "{name}" in data["welcome"], "chỗ điền tên bị mất khi truyền sang trình duyệt"
    for key in ("start", "consent", "placeholder", "branch_any", "open_chat", "send"):
        assert data.get(key), f"thiếu chuỗi '{key}' cho {locale}"


@pytest.mark.parametrize("locale", sorted(SUPPORTED_LOCALES))
def test_nothing_can_close_the_script_tag_early(locale):
    """The blob is rendered inside <script>. A translation containing "</" would
    end the tag there and take the rest of the page with it."""
    assert "</" not in _chat_copy(locale)


def test_a_missing_translation_falls_back_rather_than_vanishing():
    """English is the backstop: a key absent from a locale must still arrive with
    something readable in it, never an empty panel."""
    from backend.app.services.i18n import UI_TEXT

    english = json.loads(_chat_copy("en").replace("<\\/", "</"))
    for locale in SUPPORTED_LOCALES:
        data = json.loads(_chat_copy(locale).replace("<\\/", "</"))
        assert set(data) >= set(english), f"{locale} thiếu khoá so với tiếng Anh"
        assert all(data[k] for k in UI_TEXT["en"]), f"{locale} có chuỗi rỗng"
