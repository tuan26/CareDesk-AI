"""Server-rendered public landing pages, mounted at /book (outside /api/v1).

These are rendered by FastAPI rather than the React SPA because the crawlers
that matter here — Facebook, Zalo, Google — do not reliably run JavaScript. A
client-rendered page yields an empty <div id="root"> and the hardcoded SPA title
in every link preview, which breaks exactly the ads/SEO use case landing pages
exist for.
"""
import html
import json
import re
from datetime import date, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.models.models import BookingRequest, PatientLead
from backend.app.services.events import emit_event
from backend.app.services.landing import (
    BrandView, BranchView, NotFound, Redirect, branch_url, brand_url, chat_url,
    load_branch, load_brand,
)
from backend.app.services.features import MULTILANG, is_enabled
from backend.app.services.i18n import SUPPORTED_LOCALES, landing_text, normalize_locale, service_content
from backend.app.services.rate_limit import landing_rate_limiter

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Public pages are read-mostly and get hammered when an ad campaign runs.
_CACHE_HEADER = "public, max-age=300"


def _abs(path: str) -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}{path}"


def _pick_locale(request: Request, default: str, multilang: bool = True) -> str:
    """?lang= wins, then a previous choice, then the clinic default.

    The query parameter is what a shared link carries and what hreflang points
    at, so it has to beat the cookie - otherwise sending someone the English URL
    would still show them Vietnamese.

    With multilang off the clinic's own language is the only one served. A
    clinic that has not translated its service descriptions would otherwise
    render English chrome around Vietnamese content, which reads as a bug.
    """
    if not multilang:
        return normalize_locale(default)
    q = request.query_params.get("lang")
    if q and normalize_locale(q, default) == q.lower():
        return q.lower()
    return normalize_locale(request.cookies.get("caredesk_lang"), default)


def _localized(response, locale: str):
    """Remember the visitor's language for the next page they open."""
    response.set_cookie("caredesk_lang", locale, max_age=60 * 60 * 24 * 365,
                        samesite="lax", httponly=False)
    return response


def _not_found() -> HTMLResponse:
    body = (
        "<!doctype html><html lang=vi><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>Không tìm thấy trang</title><meta name=robots content=noindex>"
        "<style>body{font-family:system-ui,sans-serif;background:#f0fdfa;display:flex;"
        "align-items:center;justify-content:center;min-height:100vh;margin:0}"
        ".c{background:#fff;border-radius:16px;padding:40px;max-width:420px;text-align:center;"
        "box-shadow:0 10px 30px rgba(0,0,0,.08)}h2{color:#0f172a}p{color:#64748b;font-size:14px}"
        "</style></head><body><div class=c><div style='font-size:44px'>🔍</div>"
        "<h2>Không tìm thấy trang</h2>"
        "<p>Phòng khám hoặc cơ sở này không tồn tại, đã đổi liên kết hoặc đang tạm ngưng.</p>"
        "</div></body></html>"
    )
    return HTMLResponse(body, status_code=404)


def _clean(text: str | None, limit: int = 300) -> str:
    """Collapse to a single line safe for a meta tag."""
    if not text:
        return ""
    flat = " ".join(html.unescape(str(text)).split())
    return flat[: limit - 1] + "…" if len(flat) > limit else flat


def _geo(branch) -> dict:
    """schema.org geo. Coordinates are what let a clinic surface on a map result
    rather than only in a text search, so they are worth the two extra columns."""
    if branch.latitude is None or branch.longitude is None:
        return {}
    return {"geo": {"@type": "GeoCoordinates",
                    "latitude": branch.latitude, "longitude": branch.longitude}}


def _brand_json_ld(brand: BrandView, path: str) -> str:
    """Schema.org so Google can show address/phone/hours as a rich result."""
    data = {
        "@context": "https://schema.org",
        "@type": "MedicalClinic",
        "name": brand.name,
        "url": _abs(path),
    }
    if brand.og_image_url:
        data["image"] = brand.og_image_url
    if brand.phone:
        data["telephone"] = brand.phone
    if brand.address:
        data["address"] = {"@type": "PostalAddress", "streetAddress": brand.address}
    if brand.branches:
        data["location"] = [
            {
                "@type": "MedicalClinic",
                "name": b.name,
                "address": {"@type": "PostalAddress", "streetAddress": b.address},
                **({"telephone": b.phone} if b.phone else {}),
                **({"openingHours": b.working_hours} if b.working_hours else {}),
                **_geo(b),
            }
            for b in brand.branches
        ]
    return json.dumps(data, ensure_ascii=False)


def _branch_json_ld(brand: BrandView, branch: BranchView, path: str) -> str:
    data = {
        "@context": "https://schema.org",
        "@type": "MedicalClinic",
        "name": f"{brand.name} — {branch.name}",
        "url": _abs(path),
        "address": {"@type": "PostalAddress", "streetAddress": branch.address},
    }
    if brand.og_image_url:
        data["image"] = brand.og_image_url
    if branch.phone or brand.phone:
        data["telephone"] = branch.phone or brand.phone
    if branch.working_hours:
        data["openingHours"] = branch.working_hours
    data.update(_geo(branch))
    if branch.map_url:
        data["hasMap"] = branch.map_url
    return json.dumps(data, ensure_ascii=False)


# --- Booking form -----------------------------------------------------------
# Registered BEFORE /{brand}/{branch} or "dat-lich" is matched as a branch slug.
# ("dat-lich" is also a reserved slug, so no branch can shadow it either way.)
#
# Why a form at all, when the AI can book inside the chat: a real share of
# patients will not chat. Older patients especially, and anyone who just wants
# it done — they open the chat, see a conversation starting, and close the tab.
# That is a lost booking, which is the exact thing this product is sold on.
# Server-rendered and JS-free: every step is a plain link or a form POST, so it
# works on any phone and any connection.

_MAX_DAYS_AHEAD = 30


def _booking_context(db: Session, brand, branch_slug, service_id, day, doctor_id,
                     locale: str, multilang: bool) -> dict:
    """Resolve however far through the form the patient has got."""
    from backend.app.services.booking_flow import open_slots

    branches = [b for b in brand.branches] or []
    branch = next((b for b in branches if b.slug == branch_slug), None)
    if branch is None and len(branches) == 1:
        branch = branches[0]          # single location: never ask

    service = next((s for s in brand.services if str(s.id) == str(service_id)), None)

    today = date.today()
    days = [today + timedelta(days=i) for i in range(_MAX_DAYS_AHEAD)]

    chosen_day = None
    if day:
        try:
            parsed = date.fromisoformat(day)
            if today <= parsed <= today + timedelta(days=_MAX_DAYS_AHEAD):
                chosen_day = parsed
        except ValueError:
            chosen_day = None

    slots = []
    if branch and service and chosen_day:
        slots = open_slots(
            db, clinic_id=getattr(branch, "clinic_id", None) or (brand.clinic_ids[0] if brand.clinic_ids else None),
            target_date=chosen_day, duration=service.duration_minutes or 30,
            branch_id=branch.id,
            doctor_id=int(doctor_id) if doctor_id else None,
        )

    return {
        "branches": branches, "branch": branch,
        "service": service, "days": days, "chosen_day": chosen_day,
        "slots": slots,
        "doctors": brand.doctors,
        "doctor_id": doctor_id,
    }


@router.get("/{slug}/dat-lich", response_class=HTMLResponse,
            dependencies=[Depends(landing_rate_limiter)])
def booking_form(slug: str, request: Request, db: Session = Depends(get_db),
                 branch: str = "", service: str = "", day: str = "",
                 doctor: str = "", err: str = "", done: str = "", when: str = ""):
    try:
        brand = load_brand(db, slug)
    except Redirect as r:
        return RedirectResponse(f"{r.location}/dat-lich", status_code=301)
    except NotFound:
        return _not_found()

    multilang = is_enabled(db, brand.clinic_ids[0] if brand.clinic_ids else None, MULTILANG)
    locale = _pick_locale(request, brand.default_locale, multilang)
    path = f"{brand_url(brand.slug)}/dat-lich"
    ctx = _booking_context(db, brand, branch, service, day, doctor, locale, multilang)

    response = templates.TemplateResponse(
        request, "booking.html",
        {
            "brand": brand,
            "heading": landing_text(locale, "form_title"),
            "page_title": f"{landing_text(locale, 'form_title')} — {brand.name}",
            "page_description": landing_text(locale, "form_desc", name=brand.name),
            "canonical_path": path,
            "base_url": settings.PUBLIC_BASE_URL.rstrip("/"),
            "chat_href": chat_url(brand.slug),
            "json_ld": _brand_json_ld(brand, path),
            "locale": locale,
            "locales": sorted(SUPPORTED_LOCALES) if multilang else [],
            "t": lambda key, **kw: landing_text(locale, key, **kw),
            "svc": lambda s: service_content(s, locale),
            "error": err,
            "done": bool(done),
            "when": when,
            **ctx,
        },
        # A half-filled form must never be served from a cache to the next visitor.
        headers={"Cache-Control": "no-store"},
    )
    return _localized(response, locale)


@router.post("/{slug}/dat-lich", response_class=HTMLResponse,
             dependencies=[Depends(landing_rate_limiter)])
async def booking_submit(slug: str, request: Request, db: Session = Depends(get_db)):
    """Record the request. Deliberately does NOT create an Appointment.

    Same rule the public chat follows: anything arriving from an unauthenticated
    visitor becomes a BookingRequest that staff confirm. It keeps the doctor's
    calendar under the clinic's control and means a bot filling in the form
    cannot occupy real slots.
    """
    from backend.app.services.booking_flow import open_slots

    try:
        brand = load_brand(db, slug)
    except (Redirect, NotFound):
        return _not_found()

    form = await request.form()
    clinic_id = brand.clinic_ids[0] if brand.clinic_ids else None
    base = f"{brand_url(brand.slug)}/dat-lich"
    keep = (f"?branch={form.get('branch_slug', '')}&service={form.get('service_id', '')}"
            f"&day={form.get('day', '')}&doctor={form.get('doctor_id', '')}")

    def _back(message: str):
        return RedirectResponse(f"{base}{keep}&err={quote(message)}", status_code=303)

    full_name = (form.get("full_name") or "").strip()
    phone = (form.get("phone") or "").strip()
    if len(full_name) < 2:
        return _back("Vui lòng nhập họ tên.")
    if not re.fullmatch(r"0\d{8,10}", phone):
        return _back("Số điện thoại chưa đúng. Ví dụ: 0901234567")
    if not form.get("consent"):
        return _back("Vui lòng đồng ý cho phòng khám liên hệ lại.")

    service = next((s for s in brand.services if str(s.id) == str(form.get("service_id"))), None)
    branch = next((b for b in brand.branches if b.slug == form.get("branch_slug")), None)
    if not service or not branch:
        return _back("Vui lòng chọn cơ sở và dịch vụ.")

    day, slot = form.get("day", ""), form.get("slot", "")
    # Re-check the slot server-side: the page may have been open for an hour.
    try:
        target = date.fromisoformat(day)
    except ValueError:
        return _back("Vui lòng chọn ngày khám.")
    free = open_slots(db, clinic_id, target, service.duration_minutes or 30,
                      branch_id=branch.id,
                      doctor_id=int(form["doctor_id"]) if form.get("doctor_id") else None)
    if slot not in {s.strftime("%H:%M") for s, _ in free}:
        return _back("Khung giờ vừa chọn không còn trống. Vui lòng chọn giờ khác.")

    patient = PatientLead(
        clinic_id=clinic_id, full_name=full_name, phone=phone, source="web_form",
        consent_given=True, consent_timestamp=datetime.now(),
    )
    db.add(patient)
    db.flush()
    db.add(BookingRequest(
        clinic_id=clinic_id, patient_id=patient.id, service_id=service.id,
        service_or_need=service.name,
        preferred_time=f"{slot} {target.strftime('%d/%m/%Y')} — {branch.name}",
        full_name=full_name, contact_method="phone", contact_value=phone,
        note=(form.get("note") or "").strip() or None,
        locale=normalize_locale(form.get("locale") or brand.default_locale),
    ))
    emit_event(db, clinic_id, "booking_request_created", patient_id=patient.id,
               payload={"service_id": service.id, "service_name": service.name,
                        "source": "web_form"})
    db.commit()

    return RedirectResponse(f"{base}?done=1&when={quote(slot + ' ' + target.strftime('%d/%m/%Y'))}",
                            status_code=303)


@router.get("/{slug}", response_class=HTMLResponse,
            dependencies=[Depends(landing_rate_limiter)])
def brand_landing(slug: str, request: Request, db: Session = Depends(get_db)):
    try:
        brand = load_brand(db, slug)
    except Redirect as r:
        return RedirectResponse(r.location, status_code=301)
    except NotFound:
        return _not_found()

    multilang = is_enabled(db, brand.clinic_ids[0] if brand.clinic_ids else None, MULTILANG)
    locale = _pick_locale(request, brand.default_locale, multilang)
    path = brand_url(brand.slug)
    where = f" — {brand.address}" if brand.address else ""
    desc = _clean(landing_text(
        locale, "meta_desc", name=brand.name, where=where,
        branches=len(brand.branches), services=len(brand.services),
    ))
    response = templates.TemplateResponse(
        request, "brand.html",
        {
            "brand": brand,
            "heading": brand.name,
            "page_title": f"{brand.name} — {landing_text(locale, 'title_suffix')}",
            "page_description": desc,
            "canonical_path": path,
            "base_url": settings.PUBLIC_BASE_URL.rstrip("/"),
            "chat_href": chat_url(brand.slug),
            "json_ld": _brand_json_ld(brand, path),
            "locale": locale,
            "locales": sorted(SUPPORTED_LOCALES) if multilang else [],
            "t": lambda key, **kw: landing_text(locale, key, **kw),
            "svc": lambda s: service_content(s, locale),
        },
        headers={"Cache-Control": _CACHE_HEADER},
    )
    return _localized(response, locale)


@router.get("/{brand_slug}/{branch_slug}", response_class=HTMLResponse,
            dependencies=[Depends(landing_rate_limiter)])
def branch_landing(brand_slug: str, branch_slug: str, request: Request,
                   db: Session = Depends(get_db)):
    try:
        brand, branch = load_branch(db, brand_slug, branch_slug)
    except Redirect as r:
        return RedirectResponse(r.location, status_code=301)
    except NotFound:
        return _not_found()

    multilang = is_enabled(db, brand.clinic_ids[0] if brand.clinic_ids else None, MULTILANG)
    locale = _pick_locale(request, brand.default_locale, multilang)
    path = branch_url(brand.slug, branch.slug)
    hours = landing_text(locale, "meta_hours", hours=branch.working_hours) if branch.working_hours else ""
    desc = _clean(landing_text(
        locale, "meta_branch_desc", brand=brand.name, name=branch.name,
        address=branch.address, hours=hours,
    ))
    response = templates.TemplateResponse(
        request, "branch.html",
        {
            "brand": brand,
            "branch": branch,
            "heading": f"{branch.name}",
            "page_title": f"{branch.name} — {brand.name}",
            "page_description": desc,
            "canonical_path": path,
            "base_url": settings.PUBLIC_BASE_URL.rstrip("/"),
            "chat_href": chat_url(brand.slug, branch.slug),
            "json_ld": _branch_json_ld(brand, branch, path),
            "locale": locale,
            "locales": sorted(SUPPORTED_LOCALES) if multilang else [],
            "t": lambda key, **kw: landing_text(locale, key, **kw),
            "svc": lambda s: service_content(s, locale),
        },
        headers={"Cache-Control": _CACHE_HEADER},
    )
    return _localized(response, locale)
