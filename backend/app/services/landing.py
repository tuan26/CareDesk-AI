"""Public landing pages: slug resolution and view-model assembly.

URL contract (see KE_HOACH_LANDING_PHASE1.md §4):

    /book/<brand>            brand landing — the clinic's public "website"
    /book/<brand>/<branch>   one physical location

`<brand>` is the Organization slug. Clinic never appears in a public URL: it is
the billing/tenant layer, and hiding it keeps the URL stable if a clinic is
later split (e.g. by specialty). Every clinic has an organization — the platform
auto-creates a personal one for "không thuộc chuỗi" tenants — but a clinic whose
organization_id is somehow NULL still falls back to acting as its own brand
rather than becoming unreachable.
"""
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.slug import current_slug, resolve
from backend.app.services import site_content
from backend.app.models.models import (
    Branch, Clinic, Doctor, Organization, Service, SlugRegistry,
)


# ---------------------------------------------------------------- URL builders

def brand_url(brand_slug: str) -> str:
    return f"/book/{brand_slug}"


def branch_url(brand_slug: str, branch_slug: str) -> str:
    return f"/book/{brand_slug}/{branch_slug}"


def chat_url(brand_slug: str, branch_slug: str | None = None) -> str:
    """Absolute URL of the chat page.

    /chat/* is a route of the React app, not of this process. A relative link
    works only when the SPA and these landing pages share a host — true in
    production, false in development where the landing is on :8000 and Vite on
    :5173, so the link 404s. Built from FRONTEND_BASE_URL, which equals
    PUBLIC_BASE_URL in production and so changes nothing there.
    """
    path = f"/chat/{brand_slug}/{branch_slug}" if branch_slug else f"/chat/{brand_slug}"
    return f"{settings.FRONTEND_BASE_URL.rstrip('/')}{path}"


# ---------------------------------------------------------------- view models

@dataclass
class BranchView:
    id: int
    name: str
    slug: str
    address: str
    phone: Optional[str]
    working_hours: Optional[str]
    landing_enabled: bool
    # Directions. A street address is not directions — patients want a tap that
    # opens their map app.
    map_url: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


@dataclass
class ShowcaseCase:
    """One before/after pair, ready for the public page.

    Assembled from photos that already exist as clinical records — the clinic
    chooses which ones may be shown, it does not produce them for the website.
    Only photos with recorded consent AND publication ever reach here.
    """
    title: str
    before_url: Optional[str]
    after_url: Optional[str]
    service_name: Optional[str] = None


@dataclass
class PublicReview:
    """A review the clinic chose to show, under a name staff entered by hand."""
    rating: int
    text: str
    name: str


@dataclass
class BrandView:
    """Everything a brand landing page renders. Assembled from existing data —
    Phase 1 adds no content columns."""
    slug: str
    name: str
    logo_url: Optional[str]
    og_image_url: Optional[str]
    address: Optional[str]
    phone: Optional[str]
    clinic_ids: list[int]
    default_locale: str = "vi"
    branches: list[BranchView] = field(default_factory=list)
    services: list[Service] = field(default_factory=list)
    doctors: list[Doctor] = field(default_factory=list)
    is_chain: bool = False
    # Editable copy, plus the two things that actually convert an aesthetics
    # visitor: results they can see, and words from people who went first.
    content: dict = field(default_factory=dict)
    cases: list["ShowcaseCase"] = field(default_factory=list)
    reviews: list["PublicReview"] = field(default_factory=list)


# ---------------------------------------------------------------- resolution

class Redirect(Exception):
    """Raised to signal a 301 to the canonical URL."""

    def __init__(self, location: str):
        self.location = location
        super().__init__(location)


class NotFound(Exception):
    pass


def brand_slug_for_clinic(db: Session, clinic: Clinic) -> str:
    """The public brand slug a clinic lives under."""
    if clinic.organization_id:
        org = db.query(Organization).filter(Organization.id == clinic.organization_id).first()
        if org and org.slug:
            return org.slug
    return clinic.slug  # defensive: org-less clinic is its own brand


def canonical_url(db: Session, row: SlugRegistry) -> str:
    """Where a given entity's public page actually lives."""
    if row.entity_type == "organization":
        org = db.query(Organization).filter(Organization.id == row.entity_id).first()
        if not org or not org.slug:
            raise NotFound()
        return brand_url(org.slug)

    if row.entity_type == "clinic":
        clinic = db.query(Clinic).filter(Clinic.id == row.entity_id).first()
        if not clinic:
            raise NotFound()
        return brand_url(brand_slug_for_clinic(db, clinic))

    if row.entity_type == "branch":
        branch = db.query(Branch).filter(Branch.id == row.entity_id).first()
        if not branch:
            raise NotFound()
        clinic = db.query(Clinic).filter(Clinic.id == branch.clinic_id).first()
        if not clinic:
            raise NotFound()
        return branch_url(brand_slug_for_clinic(db, clinic), branch.slug)

    raise NotFound()


def _live_row(db: Session, slug: str) -> SlugRegistry:
    """Resolve a slug, redirecting retired ones and rejecting reserved words."""
    row = resolve(db, slug)
    if row is None or row.entity_type == "reserved":
        raise NotFound()
    if not row.is_active:
        # Old slug kept for exactly this: printed QR codes keep working.
        target = current_slug(db, row.entity_type, row.entity_id)
        if not target:
            raise NotFound()
        raise Redirect(canonical_url(db, resolve(db, target)))
    return row


def _load_cases(db: Session, clinic_ids: list[int], limit: int = 6) -> list["ShowcaseCase"]:
    """Published before/after pairs.

    Both conditions are required, every time: the patient consented AND the
    clinic published. The query is the enforcement point — nothing downstream
    re-checks, so this filter is the only thing between a clinical photograph
    and the open internet.
    """
    from backend.app.models.models import Appointment, VisitPhoto, VisitRecord

    photos = (
        db.query(VisitPhoto)
        .filter(VisitPhoto.clinic_id.in_(clinic_ids),
                VisitPhoto.is_published == True,           # noqa: E712
                VisitPhoto.consent_given_at != None)       # noqa: E711
        .order_by(VisitPhoto.id.desc())
        .limit(limit * 4)
        .all()
    )

    grouped: dict = {}
    for photo in photos:
        # Photos of one treatment are paired by group; anything ungrouped falls
        # back to its own visit, so a lone "after" still shows rather than
        # vanishing because nobody filled in a group name.
        key = photo.showcase_group or f"visit-{photo.visit_record_id}"
        grouped.setdefault(key, []).append(photo)

    cases = []
    for key, items in grouped.items():
        before = next((p for p in items if p.kind == "before"), None)
        after = next((p for p in items if p.kind == "after"), None)
        if not before and not after:
            continue
        lead = after or before
        record = lead.visit
        appt = record.appointment if record else None
        cases.append(ShowcaseCase(
            title=(lead.public_title
                   or (appt.service.name if appt and appt.service else "Kết quả điều trị")),
            before_url=f"/api/v1/visits/photos/{before.id}" if before else None,
            after_url=f"/api/v1/visits/photos/{after.id}" if after else None,
            service_name=appt.service.name if appt and appt.service else None,
        ))
        if len(cases) >= limit:
            break
    return cases


def _load_reviews(db: Session, clinic_ids: list[int], limit: int = 6) -> list["PublicReview"]:
    from backend.app.models.models import ReviewRequest

    rows = (
        db.query(ReviewRequest)
        .filter(ReviewRequest.clinic_id.in_(clinic_ids),
                ReviewRequest.is_published == True)        # noqa: E712
        .order_by(ReviewRequest.published_at.desc())
        .limit(limit)
        .all()
    )
    return [
        PublicReview(rating=r.rating or 5, text=r.feedback or "",
                     name=r.public_name or "Khách hàng")
        for r in rows if r.feedback
    ]


def _build_brand(db: Session, *, org: Organization | None, clinics: list[Clinic],
                 slug: str, name: str) -> BrandView:
    clinic_ids = [c.id for c in clinics]
    if not clinic_ids:
        raise NotFound()

    branches = (
        db.query(Branch)
        .filter(Branch.clinic_id.in_(clinic_ids), Branch.is_active == True)  # noqa: E712
        .order_by(Branch.id)
        .all()
    )
    services = (
        db.query(Service)
        .filter(Service.clinic_id.in_(clinic_ids))
        .order_by(Service.price)
        .all()
    )
    doctors = (
        db.query(Doctor)
        .filter(Doctor.clinic_id.in_(clinic_ids), Doctor.is_active == True)  # noqa: E712
        .order_by(Doctor.id)
        .all()
    )
    primary = clinics[0]
    return BrandView(
        slug=slug,
        name=name,
        logo_url=next((c.logo_url for c in clinics if c.logo_url), None),
        # Prefer a purpose-made share image; a logo is better than nothing but
        # is usually too small for crawlers to accept.
        og_image_url=next(
            (c.og_image_url for c in clinics if c.og_image_url),
            next((c.logo_url for c in clinics if c.logo_url), None),
        ),
        address=primary.address,
        phone=primary.phone,
        default_locale=primary.default_locale or "vi",
        clinic_ids=clinic_ids,
        branches=[
            BranchView(
                id=b.id, name=b.name, slug=b.slug or "", address=b.address,
                phone=b.phone, working_hours=b.working_hours,
                landing_enabled=bool(b.landing_enabled),
                map_url=b.map_url, latitude=b.latitude, longitude=b.longitude,
            )
            for b in branches if b.slug
        ],
        services=services,
        doctors=doctors,
        is_chain=bool(org and len(clinics) > 1),
        content=site_content.load(db, clinic_ids[0]),
        cases=_load_cases(db, clinic_ids),
        reviews=_load_reviews(db, clinic_ids),
    )


def load_brand(db: Session, slug: str) -> BrandView:
    """Resolve /book/<slug> to a brand landing, or raise Redirect / NotFound."""
    row = _live_row(db, slug)

    if row.entity_type == "branch":
        raise Redirect(canonical_url(db, row))  # branch lives one level deeper

    if row.entity_type == "clinic":
        clinic = db.query(Clinic).filter(Clinic.id == row.entity_id).first()
        if not clinic:
            raise NotFound()
        brand = brand_slug_for_clinic(db, clinic)
        if brand != slug:
            raise Redirect(brand_url(brand))  # clinic slug -> its organization
        if not clinic.is_active or not clinic.landing_enabled:
            raise NotFound()
        return _build_brand(db, org=None, clinics=[clinic], slug=slug, name=clinic.name)

    # organization
    org = db.query(Organization).filter(Organization.id == row.entity_id).first()
    if not org or not org.is_active or not org.landing_enabled:
        raise NotFound()
    clinics = (
        db.query(Clinic)
        .filter(Clinic.organization_id == org.id,
                Clinic.is_active == True,  # noqa: E712
                Clinic.landing_enabled == True)  # noqa: E712
        .order_by(Clinic.id)
        .all()
    )
    if not clinics:
        raise NotFound()
    return _build_brand(db, org=org, clinics=clinics, slug=slug, name=org.name)


def load_branch(db: Session, brand_slug: str, branch_slug: str) -> tuple[BrandView, BranchView]:
    """Resolve /book/<brand>/<branch>, handling the legacy /book/<org>/<clinic> shape."""
    # Resolve the brand without redirecting on a retired slug: the canonical
    # check at the end already redirects, and it knows the branch — going
    # through _live_row here would send /book/<old-brand>/<branch> to the brand
    # page and silently drop the branch the visitor asked for.
    brand_row = resolve(db, brand_slug)
    if brand_row is None or brand_row.entity_type == "reserved":
        raise NotFound()
    child_row = _live_row(db, branch_slug)

    # Legacy URL: second segment used to be the clinic. Send it to the brand page.
    if child_row.entity_type == "clinic":
        raise Redirect(canonical_url(db, child_row))

    if child_row.entity_type != "branch":
        raise NotFound()

    branch = db.query(Branch).filter(Branch.id == child_row.entity_id).first()
    if not branch or not branch.is_active or not branch.landing_enabled:
        raise NotFound()

    clinic = db.query(Clinic).filter(Clinic.id == branch.clinic_id).first()
    if not clinic or not clinic.is_active:
        raise NotFound()

    # The branch must actually live under the brand in the URL, and the brand
    # must be spelled canonically — otherwise redirect rather than serve the
    # same page at two URLs (duplicate content).
    real_brand = brand_slug_for_clinic(db, clinic)
    if real_brand != brand_slug or brand_row.entity_type not in ("organization", "clinic"):
        raise Redirect(branch_url(real_brand, branch.slug))

    brand = load_brand(db, real_brand)
    view = next((b for b in brand.branches if b.id == branch.id), None)
    if view is None:  # inactive/hidden at the brand level
        raise NotFound()
    return brand, view
