"""Public URL slugs, allocated through the global `slug_registry`.

Two rules this module exists to enforce:

1. **Global uniqueness.** Organizations, clinics and branches share one public
   namespace (/book/<slug>). Per-table UNIQUE columns would let a clinic and a
   branch claim the same slug and route a patient to the wrong clinic, so every
   slug is allocated against one registry table whose primary key is the slug.

2. **Slugs are immutable on rename.** Renaming "Bạch Mai" to "Bệnh viện Bạch Mai
   Cơ sở 2" must NOT change /book/.../bach-mai — printed QR codes, shared links
   and Google's index all point at the old URL. Changing a slug is a separate,
   explicit action (`change_slug`), and even then the old slug is retained so it
   can be 301-redirected.

Brand-level entities (organization, clinic) get a random suffix so tenants can't
enumerate each other's public links. Branch slugs stay readable ('bach-mai') —
they sit behind an already-unguessable brand slug, and readability is the whole
point of /book/<brand>/<branch>.
"""
import re
import secrets
import unicodedata
from sqlalchemy.orm import Session

from backend.app.models.models import SlugRegistry

# Mirrors the seed list in the f6a7b8c9d0e1 migration. Kept here so a fresh DB
# created outside migrations still refuses to hand these out.
RESERVED_SLUGS = frozenset({
    "admin", "api", "app", "auth", "assets", "static", "public", "uploads",
    "media", "book", "chat", "login", "logout", "register", "signup", "signin",
    "dashboard", "settings", "account", "profile", "platform", "org", "clinic",
    "branch", "health", "healthz", "status", "docs", "openapi", "swagger",
    "redoc", "graphql", "ws", "webhooks", "search", "help", "support",
    "pricing", "about", "contact", "privacy", "terms", "blog", "news",
    "robots.txt", "favicon.ico", "sitemap.xml", "manifest.json",
})

_TYPE_BY_TABLE = {
    "organizations": "organization",
    "clinics": "clinic",
    "branches": "branch",
}
# Brand-level slugs are public entry points -> unguessable. Branch slugs are
# nested under one and stay readable.
_TOKENISED_TYPES = {"organization", "clinic"}


def slugify(text: str) -> str:
    """'Phòng khám Da liễu ABC' -> 'phong-kham-da-lieu-abc'."""
    if not text:
        return ""
    text = text.replace("đ", "d").replace("Đ", "D")
    # Strip diacritics
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "clinic"


def entity_type_of(obj) -> str:
    """Map an ORM instance to its registry entity_type."""
    table = obj.__tablename__
    try:
        return _TYPE_BY_TABLE[table]
    except KeyError:
        raise ValueError(f"{table} does not take a public slug") from None


def is_available(db: Session, slug: str, *, owner: tuple[str, int] | None = None) -> bool:
    """True if `slug` can be used. A slug the owner already holds counts as free."""
    if not slug or slug in RESERVED_SLUGS:
        return False
    row = db.query(SlugRegistry).filter(SlugRegistry.slug == slug).first()
    if row is None:
        return True
    if owner and row.entity_type == owner[0] and row.entity_id == owner[1]:
        return True  # re-claiming a slug we already own (incl. a retired one)
    return False


def resolve(db: Session, slug: str) -> SlugRegistry | None:
    """Look up any public slug in one indexed query.

    Returns the registry row (check `.is_active` — False means the caller should
    301 to the entity's current slug) or None when the slug is unknown.
    """
    return db.query(SlugRegistry).filter(SlugRegistry.slug == slug).first()


def current_slug(db: Session, entity_type: str, entity_id: int) -> str | None:
    """The live slug for an entity — used to build 301 targets for retired slugs."""
    row = (
        db.query(SlugRegistry)
        .filter(
            SlugRegistry.entity_type == entity_type,
            SlugRegistry.entity_id == entity_id,
            SlugRegistry.is_active == True,  # noqa: E712
        )
        .first()
    )
    return row.slug if row else None


def _allocate(db: Session, entity_type: str, entity_id: int, base: str) -> str:
    """Find a free slug derived from `base` and register it."""
    stem = slugify(base) or entity_type
    owner = (entity_type, entity_id)

    if entity_type in _TOKENISED_TYPES:
        candidates = (f"{stem}-{secrets.token_hex(3)}" for _ in iter(int, 1))
    else:
        def _readable():
            yield stem
            while True:
                yield f"{stem}-{secrets.token_hex(3)}"
        candidates = _readable()

    for candidate in candidates:
        if is_available(db, candidate, owner=owner):
            existing = db.query(SlugRegistry).filter(SlugRegistry.slug == candidate).first()
            if existing is not None:
                existing.is_active = True  # revive a slug this entity used before
            else:
                db.add(SlugRegistry(
                    slug=candidate, entity_type=entity_type,
                    entity_id=entity_id, is_active=True,
                ))
            db.flush()
            return candidate
    raise RuntimeError("unreachable")  # generators above are infinite


def assign_slug(db: Session, obj, base: str | None = None) -> str:
    """Give `obj` its first slug (no-op if it already has one).

    Safe to call on every save: it will not churn the URL of an entity that is
    already published. Use `change_slug` to deliberately move a URL.
    """
    if getattr(obj, "slug", None):
        return obj.slug
    entity_type = entity_type_of(obj)
    if obj.id is None:
        db.flush()  # need the PK before we can register ownership
    slug = _allocate(db, entity_type, obj.id, base or obj.name)
    obj.slug = slug
    return slug


def change_slug(db: Session, obj, new_base: str) -> str:
    """Deliberately move an entity to a new public URL.

    The previous slug is kept in the registry with is_active=False so old links
    and printed QR codes can be 301-redirected instead of 404ing.
    """
    entity_type = entity_type_of(obj)
    desired = slugify(new_base)
    if not desired:
        raise ValueError("Slug không hợp lệ.")
    if desired == obj.slug:
        return obj.slug  # nothing to do — never churn a live URL
    if not is_available(db, desired, owner=(entity_type, obj.id)):
        raise ValueError(f"Slug '{desired}' đã được sử dụng.")

    db.query(SlugRegistry).filter(
        SlugRegistry.entity_type == entity_type,
        SlugRegistry.entity_id == obj.id,
        SlugRegistry.is_active == True,  # noqa: E712
    ).update({SlugRegistry.is_active: False}, synchronize_session=False)

    existing = db.query(SlugRegistry).filter(SlugRegistry.slug == desired).first()
    if existing is not None:
        existing.is_active = True
    else:
        db.add(SlugRegistry(
            slug=desired, entity_type=entity_type, entity_id=obj.id, is_active=True,
        ))
    obj.slug = desired
    db.flush()
    return desired
