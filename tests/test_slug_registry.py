import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.core.slug import (
    assign_slug, change_slug, current_slug, is_available, resolve, slugify,
)
from backend.app.models.models import Branch, Clinic, Organization, SlugRegistry

engine = create_engine("sqlite:///:memory:")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=engine)
    s = TestingSessionLocal()
    yield s
    s.close()
    Base.metadata.drop_all(bind=engine)


def _clinic(db, name="Phòng khám Da liễu ABC"):
    c = Clinic(name=name, is_active=True)
    db.add(c)
    db.flush()
    assign_slug(db, c)
    return c


def _branch(db, clinic, name="Bạch Mai"):
    b = Branch(clinic_id=clinic.id, name=name, address="123 Bạch Mai")
    db.add(b)
    db.flush()
    assign_slug(db, b)
    return b


def test_branch_slug_is_readable_clinic_slug_is_tokenised(db):
    """Branch URLs are the human-facing part; brand slugs stay unguessable."""
    c = _clinic(db)
    b = _branch(db, c)
    assert b.slug == "bach-mai"
    assert c.slug.startswith("phong-kham-da-lieu-abc-")
    assert c.slug != "phong-kham-da-lieu-abc"  # random suffix present


def test_renaming_does_not_change_slug(db):
    """The core rule: printed QR codes must survive a rename."""
    c = _clinic(db)
    b = _branch(db, c)
    original = b.slug

    b.name = "Bệnh viện Bạch Mai Cơ sở 2"
    assign_slug(db, b)  # called on every save
    db.flush()

    assert b.slug == original


def test_slug_is_globally_unique_across_entity_types(db):
    """A branch must not be able to steal a clinic's slug (would misroute patients)."""
    c = _clinic(db, name="Long Biên")
    b = _branch(db, c, name="Long Biên")
    assert b.slug != c.slug
    slugs = [r.slug for r in db.query(SlugRegistry).all()]
    assert len(slugs) == len(set(slugs))


def test_two_branches_same_name_get_distinct_slugs(db):
    c1 = _clinic(db, name="Chuỗi A")
    c2 = _clinic(db, name="Chuỗi B")
    b1 = _branch(db, c1, name="Hà Đông")
    b2 = _branch(db, c2, name="Hà Đông")
    assert b1.slug == "ha-dong"
    assert b2.slug != b1.slug


def test_reserved_words_are_never_handed_out(db):
    c = _clinic(db)
    b = _branch(db, c, name="Admin")
    assert b.slug != "admin"
    assert not is_available(db, "api")
    assert not is_available(db, "chat")


def test_change_slug_retires_old_one_for_redirect(db):
    c = _clinic(db)
    b = _branch(db, c)
    old = b.slug

    change_slug(db, b, "bach-mai-co-so-2")
    db.flush()

    assert b.slug == "bach-mai-co-so-2"
    retired = resolve(db, old)
    assert retired is not None, "old slug must stay resolvable for a 301"
    assert retired.is_active is False
    assert current_slug(db, "branch", b.id) == "bach-mai-co-so-2"


def test_change_slug_to_same_value_is_noop(db):
    """Resubmitting the edit form unchanged must not churn the URL."""
    c = _clinic(db)
    b = _branch(db, c)
    before = b.slug
    change_slug(db, b, before)
    assert b.slug == before
    assert db.query(SlugRegistry).filter(
        SlugRegistry.entity_type == "branch", SlugRegistry.entity_id == b.id
    ).count() == 1


def test_change_slug_rejects_taken_slug(db):
    c = _clinic(db)
    b1 = _branch(db, c, name="Bạch Mai")
    b2 = _branch(db, c, name="Linh Đàm")
    with pytest.raises(ValueError):
        change_slug(db, b2, b1.slug)


def test_resolve_returns_entity_identity(db):
    c = _clinic(db)
    b = _branch(db, c)
    row = resolve(db, b.slug)
    assert (row.entity_type, row.entity_id, row.is_active) == ("branch", b.id, True)
    assert resolve(db, "khong-ton-tai") is None


def test_slugify_handles_vietnamese(db):
    assert slugify("Phòng khám Da liễu Thẩm mỹ") == "phong-kham-da-lieu-tham-my"
    assert slugify("Đống Đa") == "dong-da"
