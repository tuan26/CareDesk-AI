"""Stepping into a clinic: an above-clinic account must land on a clinic role.

get_current_user rewrites role in memory when a token carries act_clinic_id.
Before the "admin" role was retired this mapping only covered org_owner — the
vendor kept role="admin" and happened to pass because "admin" was still in every
RoleChecker list. Remove the role without fixing the mapping and the vendor gets
403 on every clinic screen, so these tests guard the pair together.
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.api.deps import (
    ROLE_ORG_OWNER, ROLE_OWNER, ROLE_PLATFORM, ROLE_RECEPTIONIST,
    get_current_user, verify_owner,
)
from backend.app.core.database import Base
from backend.app.core.security import create_access_token
from backend.app.models.models import Clinic, Organization, User

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
    """One chain, one clinic in it, plus a clinic belonging to nobody."""
    org = Organization(name="Chuoi A", is_active=True)
    db.add(org)
    db.flush()

    mine = Clinic(name="Co so cua toi", organization_id=org.id, is_active=True)
    theirs = Clinic(name="Cua nguoi khac", is_active=True)
    db.add_all([mine, theirs])
    db.flush()

    # password_hash / full_name are NOT NULL but irrelevant to these tests.
    pw = "x"
    chain_owner = User(email="chain@x.vn", role=ROLE_ORG_OWNER, password_hash=pw,
                       full_name="Chu chuoi", organization_id=org.id,
                       clinic_id=None, is_active=True)
    vendor = User(email="platform@x.vn", role=ROLE_PLATFORM, password_hash=pw,
                  full_name="Nha phat hanh", is_platform_admin=True,
                  clinic_id=None, is_active=True)
    front_desk = User(email="letan@x.vn", role=ROLE_RECEPTIONIST, password_hash=pw,
                      full_name="Le tan", clinic_id=mine.id, is_active=True)
    db.add_all([chain_owner, vendor, front_desk])
    db.commit()
    return {"org": org, "mine": mine, "theirs": theirs,
            "chain_owner": chain_owner, "vendor": vendor, "front_desk": front_desk}


def _token(user, clinic_id=None):
    extra = {"act_clinic_id": clinic_id} if clinic_id else None
    return create_access_token(user.email, extra_claims=extra)


@pytest.mark.parametrize("who", ["chain_owner", "vendor"])
def test_stepping_in_grants_owner_of_that_clinic(db, chain, who):
    user = get_current_user(db=db, token=_token(chain[who], chain["mine"].id))
    assert user.role == ROLE_OWNER
    assert user.clinic_id == chain["mine"].id
    # ...and that role actually opens the owner-gated endpoints.
    assert verify_owner(current_user=user) is user


def test_stepping_in_is_not_written_back_to_the_database(db, chain):
    get_current_user(db=db, token=_token(chain["chain_owner"], chain["mine"].id))
    db.expire_all()
    stored = db.query(User).filter(User.email == "chain@x.vn").first()
    assert stored.role == ROLE_ORG_OWNER
    assert stored.clinic_id is None


def test_chain_owner_cannot_step_into_a_clinic_outside_their_chain(db, chain):
    user = get_current_user(db=db, token=_token(chain["chain_owner"], chain["theirs"].id))
    assert user.clinic_id is None
    assert user.role == ROLE_ORG_OWNER
    with pytest.raises(HTTPException):
        verify_owner(current_user=user)


def test_vendor_may_step_into_any_clinic(db, chain):
    """The platform admin is not bound by organization_id."""
    user = get_current_user(db=db, token=_token(chain["vendor"], chain["theirs"].id))
    assert user.clinic_id == chain["theirs"].id
    assert user.role == ROLE_OWNER


def test_clinic_staff_cannot_promote_themselves_with_a_forged_scope(db, chain):
    """A receptionist minting a token for their own clinic stays a receptionist:
    the rewrite only applies to above-clinic roles."""
    user = get_current_user(db=db, token=_token(chain["front_desk"], chain["mine"].id))
    assert user.role == ROLE_RECEPTIONIST
    with pytest.raises(HTTPException):
        verify_owner(current_user=user)


def test_no_scope_claim_leaves_the_role_untouched(db, chain):
    user = get_current_user(db=db, token=_token(chain["vendor"]))
    assert user.role == ROLE_PLATFORM
    assert user.clinic_id is None
