"""Links from a landing page must point at something that exists.

/chat/* is a route of the React app, not of the process that renders these
pages. A relative href works only while the SPA and the landing share a host —
true in production, false in development, where the landing is served on :8000
and Vite runs on :5173. "Đặt lịch với trợ lý ảo" then landed on the backend and
returned {"detail":"Not Found"}.
"""
import pytest

from backend.app.core.config import settings
from backend.app.services import landing as landing_service
from backend.app.services.landing import brand_url, branch_url, chat_url


def test_the_chat_link_is_absolute(monkeypatch):
    """Relative is what broke it: the browser resolved it against whatever host
    served the landing page."""
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "http://localhost:5173")
    url = chat_url("caredesk")
    assert url.startswith("http://"), url
    assert url == "http://localhost:5173/chat/caredesk"


def test_the_branch_variant_keeps_the_branch(monkeypatch):
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "http://localhost:5173")
    assert chat_url("caredesk", "bach-mai") == "http://localhost:5173/chat/caredesk/bach-mai"


def test_a_trailing_slash_does_not_double_up(monkeypatch):
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "https://caredesk.vn/")
    assert chat_url("caredesk") == "https://caredesk.vn/chat/caredesk"


def test_one_domain_in_production_is_unchanged(monkeypatch):
    """Vercel serves the SPA and rewrites /book/* to the backend, so both live on
    the same host and this fix must be a no-op there."""
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "https://caredesk.vn")
    assert chat_url("caredesk") == "https://caredesk.vn/chat/caredesk"


def test_landing_urls_stay_relative():
    """Only /chat/* leaves this process. The landing's own paths must remain
    relative so canonical, hreflang and sitemap keep building correctly."""
    assert brand_url("caredesk") == "/book/caredesk"
    assert branch_url("caredesk", "bach-mai") == "/book/caredesk/bach-mai"


@pytest.mark.parametrize("template", ["brand.html", "branch.html", "booking.html"])
def test_no_template_hardcodes_a_chat_path(template):
    """A hardcoded href="/chat/..." bypasses the helper and reintroduces the bug
    on whichever page it sits."""
    from pathlib import Path

    path = Path(landing_service.__file__).resolve().parents[1] / "templates" / template
    body = path.read_text(encoding="utf-8")
    assert 'href="/chat/' not in body, f"{template} còn link /chat/ tương đối"
