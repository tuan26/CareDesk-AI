"""Vietnamese-aware slug generation for public clinic/chain links."""
import re
import secrets
import unicodedata
from sqlalchemy.orm import Session


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


def unique_slug(db: Session, model, base: str, exclude_id: int | None = None) -> str:
    """Return a slug unique on `model.slug`, appending -2, -3... on collision."""
    base = slugify(base)
    candidate = base
    i = 1
    while True:
        q = db.query(model).filter(model.slug == candidate)
        if exclude_id is not None:
            q = q.filter(model.id != exclude_id)
        if not q.first():
            return candidate
        i += 1
        candidate = f"{base}-{i}"


def slug_with_token(db: Session, model, base: str, exclude_id: int | None = None) -> str:
    """
    Brandable but unguessable slug: '<name>-<random>' (e.g. 'phong-kham-abc-a4f9c2').
    The random suffix prevents enumeration/guessing of other tenants' public links,
    while keeping the URL readable. Guaranteed unique on model.slug.
    """
    base_slug = slugify(base)
    while True:
        candidate = f"{base_slug}-{secrets.token_hex(3)}"  # 6 hex chars
        q = db.query(model).filter(model.slug == candidate)
        if exclude_id is not None:
            q = q.filter(model.id != exclude_id)
        if not q.first():
            return candidate
