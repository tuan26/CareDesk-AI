import pytest
from fastapi import HTTPException, status
from backend.app.api.deps import RoleChecker
from backend.app.models.models import User

def test_role_checker_success():
    # User is admin, Checker allows admin -> Success
    checker = RoleChecker(allowed_roles=["admin"])
    user = User(email="admin@caredesk.ai", role="admin", is_active=True)
    
    result = checker(current_user=user)
    assert result == user


def test_role_checker_multiple_roles():
    # User is owner, Checker allows owner or admin -> Success
    checker = RoleChecker(allowed_roles=["owner", "admin"])
    user = User(email="owner@caredesk.ai", role="owner", is_active=True)
    
    result = checker(current_user=user)
    assert result == user


def test_role_checker_forbidden():
    # User is receptionist, Checker allows owner or admin -> Forbidden (HTTPException 403)
    checker = RoleChecker(allowed_roles=["owner", "admin"])
    user = User(email="receptionist@caredesk.ai", role="receptionist", is_active=True)
    
    with pytest.raises(HTTPException) as exc_info:
        checker(current_user=user)
        
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert "Quyền truy cập bị từ chối" in exc_info.value.detail


def test_role_checker_inactive_user():
    # User is admin but is_active = False -> Forbidden (HTTPException 400 Inactive user)
    # The get_current_active_user helper itself raises it, but we can test RoleChecker with a helper mocks
    from backend.app.api.deps import get_current_active_user
    
    inactive_user = User(email="admin@caredesk.ai", role="admin", is_active=False)
    
    with pytest.raises(HTTPException) as exc_info:
        get_current_active_user(current_user=inactive_user)
        
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Inactive user"
