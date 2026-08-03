"""robots.txt and sitemap.xml — served from the site root, not under /book.

Google will not discover landing pages on its own: they are only linked from
inside the admin console and from whatever the clinic pastes into an ad. The
sitemap is how the brand and branch pages get crawled at all.
"""
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.models.models import Branch, Clinic, Organization
from backend.app.services.landing import brand_slug_for_clinic, branch_url, brand_url

router = APIRouter()


def _base() -> str:
    return settings.PUBLIC_BASE_URL.rstrip("/")


@router.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
def robots() -> str:
    # The admin console and the JSON API hold no public content and should never
    # be indexed; /chat is a live session, not a page worth ranking.
    return (
        "User-agent: *\n"
        "Allow: /book/\n"
        "Disallow: /api/\n"
        "Disallow: /chat/\n"
        "Disallow: /platform\n"
        "Disallow: /org\n"
        f"\nSitemap: {_base()}/sitemap.xml\n"
    )


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap(db: Session = Depends(get_db)) -> Response:
    base = _base()
    urls: list[tuple[str, str]] = []  # (loc, priority)
    seen: set[str] = set()

    clinics = (
        db.query(Clinic)
        .filter(Clinic.is_active == True, Clinic.landing_enabled == True)  # noqa: E712
        .all()
    )
    for clinic in clinics:
        brand = brand_slug_for_clinic(db, clinic)
        if not brand:
            continue
        # A brand page is shared by every clinic in the organization; emit once.
        if brand not in seen:
            org = (
                db.query(Organization)
                .filter(Organization.id == clinic.organization_id)
                .first()
                if clinic.organization_id else None
            )
            if org and not (org.is_active and org.landing_enabled):
                continue
            seen.add(brand)
            urls.append((f"{base}{brand_url(brand)}", "1.0"))

        for b in (
            db.query(Branch)
            .filter(Branch.clinic_id == clinic.id,
                    Branch.is_active == True,          # noqa: E712
                    Branch.landing_enabled == True)    # noqa: E712
            .all()
        ):
            if b.slug:
                urls.append((f"{base}{branch_url(brand, b.slug)}", "0.8"))

    body = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, priority in urls:
        body.append(f"  <url><loc>{escape(loc)}</loc><priority>{priority}</priority></url>")
    body.append("</urlset>")
    return Response("\n".join(body), media_type="application/xml")
