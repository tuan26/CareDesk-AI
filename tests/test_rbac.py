"""Role model: two roles inside a clinic, two above it.

The clinic-level "admin" role was retired (migration c9d0e1f2a3b4). These tests
pin down what replaced it, so the string cannot quietly creep back in.
"""
import pytest
from fastapi import HTTPException, status

from backend.app.api.deps import (
    ABOVE_CLINIC_ROLES, CLINIC_ROLES, ROLE_OWNER, ROLE_PLATFORM,
    ROLE_RECEPTIONIST, RoleChecker, get_current_active_user,
    verify_owner, verify_receptionist_or_above,
)
from backend.app.models.models import User


def test_role_checker_success():
    checker = RoleChecker(allowed_roles=[ROLE_OWNER])
    user = User(email="owner@caredesk.ai", role=ROLE_OWNER, is_active=True)
    assert checker(current_user=user) == user


def test_role_checker_multiple_roles():
    checker = RoleChecker(allowed_roles=[ROLE_RECEPTIONIST, ROLE_OWNER])
    user = User(email="owner@caredesk.ai", role=ROLE_OWNER, is_active=True)
    assert checker(current_user=user) == user


def test_role_checker_forbidden():
    checker = RoleChecker(allowed_roles=[ROLE_OWNER])
    user = User(email="receptionist@caredesk.ai", role=ROLE_RECEPTIONIST, is_active=True)

    with pytest.raises(HTTPException) as exc_info:
        checker(current_user=user)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert "Quyền truy cập bị từ chối" in exc_info.value.detail


def test_role_checker_inactive_user():
    inactive_user = User(email="owner@caredesk.ai", role=ROLE_OWNER, is_active=False)

    with pytest.raises(HTTPException) as exc_info:
        get_current_active_user(current_user=inactive_user)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Inactive user"


# --- the retired "admin" role ------------------------------------------------

def test_admin_is_no_longer_a_role_anywhere():
    """Both halves matter: not in the vocabulary, and not accepted by a gate."""
    assert "admin" not in CLINIC_ROLES + ABOVE_CLINIC_ROLES
    assert "admin" not in verify_owner.allowed_roles
    assert "admin" not in verify_receptionist_or_above.allowed_roles


def test_a_leftover_admin_account_is_refused_not_silently_admitted():
    """If a row somehow escapes the migration it must fail loudly, not sit at
    owner-level access under a role nothing recognises."""
    stale = User(email="admin@caredesk.ai", role="admin", is_active=True)

    for gate in (verify_owner, verify_receptionist_or_above):
        with pytest.raises(HTTPException) as exc_info:
            gate(current_user=stale)
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


def test_clinic_roles_are_exactly_owner_and_receptionist():
    assert set(CLINIC_ROLES) == {ROLE_OWNER, ROLE_RECEPTIONIST}


def test_above_clinic_roles_are_not_clinic_roles():
    """org_owner / platform must not pass a clinic gate on their own — they get
    clinic access only by stepping into one, which rewrites role to owner."""
    for role in ABOVE_CLINIC_ROLES:
        assert role not in CLINIC_ROLES
        user = User(email=f"{role}@caredesk.ai", role=role, is_active=True)
        with pytest.raises(HTTPException):
            verify_receptionist_or_above(current_user=user)


def test_platform_role_is_distinct_from_the_flag_that_grants_access():
    """Access comes from is_platform_admin; the role string is only a label."""
    from backend.app.api.deps import get_platform_admin

    labelled_but_not_flagged = User(
        email="x@caredesk.ai", role=ROLE_PLATFORM,
        is_platform_admin=False, is_active=True,
    )
    with pytest.raises(HTTPException) as exc_info:
        get_platform_admin(current_user=labelled_but_not_flagged)
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
