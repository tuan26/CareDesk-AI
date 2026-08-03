import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.core.slug import assign_slug, change_slug
from backend.app.models.models import Branch, Clinic, Doctor, Organization, Service
from backend.app.services.landing import (
    NotFound, Redirect, load_branch, load_brand,
)

engine = create_engine("sqlite:///:memory:")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=engine)
    s = TestingSessionLocal()
    yield s
    s.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def chain(db):
    """Org 'CareDesk' -> one clinic -> two branches, one with a landing page."""
    org = Organization(name="CareDesk", is_active=True, landing_enabled=True)
    db.add(org)
    db.flush()
    assign_slug(db, org)

    clinic = Clinic(name="CareDesk Da lieu", organization_id=org.id,
                    is_active=True, landing_enabled=True,
                    address="1 Ba Trieu", phone="0900000000")
    db.add(clinic)
    db.flush()
    assign_slug(db, clinic)

    b1 = Branch(clinic_id=clinic.id, name="Bach Mai", address="10 Bach Mai",
                working_hours="08:00 - 20:00", landing_enabled=True, is_active=True)
    b2 = Branch(clinic_id=clinic.id, name="Ha Dong", address="20 Ha Dong",
                landing_enabled=False, is_active=True)
    db.add_all([b1, b2])
    db.flush()
    assign_slug(db, b1)
    assign_slug(db, b2)

    db.add(Service(clinic_id=clinic.id, name="Kham da lieu", price=150000, duration_minutes=30))
    db.add(Doctor(clinic_id=clinic.id, name="BS A", specialty="Da lieu",
                  branch_id=b1.id, is_active=True))
    db.commit()
    return {"org": org, "clinic": clinic, "b1": b1, "b2": b2}


def test_brand_landing_aggregates_branches_services_doctors(db, chain):
    brand = load_brand(db, chain["org"].slug)
    assert brand.name == "CareDesk"
    assert len(brand.branches) == 2
    assert len(brand.services) == 1
    assert len(brand.doctors) == 1


def test_clinic_slug_redirects_to_brand(db, chain):
    """Clinic never appears in a public URL, but its slug must not 404."""
    with pytest.raises(Redirect) as e:
        load_brand(db, chain["clinic"].slug)
    assert e.value.location == f"/book/{chain['org'].slug}"


def test_branch_slug_at_top_level_redirects_one_level_down(db, chain):
    with pytest.raises(Redirect) as e:
        load_brand(db, chain["b1"].slug)
    assert e.value.location == f"/book/{chain['org'].slug}/{chain['b1'].slug}"


def test_legacy_org_clinic_url_redirects_to_brand(db, chain):
    """The old /book/<org>/<clinic> shape must 301, never 404."""
    with pytest.raises(Redirect) as e:
        load_branch(db, chain["org"].slug, chain["clinic"].slug)
    assert e.value.location == f"/book/{chain['org'].slug}"


def test_branch_landing_requires_opt_in(db, chain):
    brand, view = load_branch(db, chain["org"].slug, chain["b1"].slug)
    assert view.name == "Bach Mai"
    assert brand.name == "CareDesk"

    with pytest.raises(NotFound):  # b2 has landing_enabled=False
        load_branch(db, chain["org"].slug, chain["b2"].slug)


def test_branch_under_wrong_brand_redirects_to_canonical(db, chain):
    """Serving one page at two URLs would be duplicate content for SEO."""
    with pytest.raises(Redirect) as e:
        load_branch(db, chain["clinic"].slug, chain["b1"].slug)
    assert e.value.location == f"/book/{chain['org'].slug}/{chain['b1'].slug}"


def test_retired_slug_redirects_to_current(db, chain):
    """A renamed URL keeps working — this is what saves printed QR codes."""
    old = chain["b1"].slug
    change_slug(db, chain["b1"], "bach-mai-co-so-2")
    db.commit()

    with pytest.raises(Redirect) as e:
        load_brand(db, old)
    assert e.value.location == f"/book/{chain['org'].slug}/bach-mai-co-so-2"


def test_retired_brand_slug_keeps_the_branch(db, chain):
    """/book/<old-brand>/<branch> must land on that branch, not the brand page."""
    old_brand = chain["org"].slug
    change_slug(db, chain["org"], "caredesk")
    db.commit()

    with pytest.raises(Redirect) as e:
        load_branch(db, old_brand, chain["b1"].slug)
    assert e.value.location == f"/book/caredesk/{chain['b1'].slug}"


def test_inactive_branch_is_hidden_everywhere(db, chain):
    chain["b1"].is_active = False
    db.commit()

    brand = load_brand(db, chain["org"].slug)
    assert [b.name for b in brand.branches] == ["Ha Dong"]
    with pytest.raises(NotFound):
        load_branch(db, chain["org"].slug, chain["b1"].slug)


def test_landing_disabled_and_unknown_slugs_404(db, chain):
    with pytest.raises(NotFound):
        load_brand(db, "khong-ton-tai")
    with pytest.raises(NotFound):
        load_brand(db, "admin")  # reserved

    chain["org"].landing_enabled = False
    db.commit()
    with pytest.raises(NotFound):
        load_brand(db, chain["org"].slug)


def test_clinic_without_org_is_its_own_brand(db):
    """Defensive: an org-less clinic must stay reachable, not 500."""
    clinic = Clinic(name="An Khang", is_active=True, landing_enabled=True, address="5 Le Loi")
    db.add(clinic)
    db.flush()
    assign_slug(db, clinic)
    branch = Branch(clinic_id=clinic.id, name="Co so chinh", address="5 Le Loi",
                    landing_enabled=True, is_active=True)
    db.add(branch)
    db.flush()
    assign_slug(db, branch)
    db.commit()

    brand = load_brand(db, clinic.slug)
    assert brand.name == "An Khang"
    _, view = load_branch(db, clinic.slug, branch.slug)
    assert view.name == "Co so chinh"
