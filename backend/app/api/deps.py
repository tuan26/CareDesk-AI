from typing import Generator, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.core.roles import (  # noqa: F401 — re-exported for endpoints
    ABOVE_CLINIC_ROLES, CLINIC_ROLES, ROLE_ORG_OWNER, ROLE_OWNER,
    ROLE_PLATFORM, ROLE_RECEPTIONIST,
)
from backend.app.models.models import User, Clinic
from backend.app.schemas.schemas import TokenData


oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")

def get_current_user(
    db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = TokenData(email=email)
    except JWTError:
        raise credentials_exception
        
    user = db.query(User).filter(User.email == token_data.email).first()
    if not user:
        raise credentials_exception

    # Scoped token: a chain owner (or platform admin) "entering" a clinic acts on it
    # with owner-level access. The clinic MUST belong to their org (re-validated here).
    act_clinic_id = payload.get("act_clinic_id")
    if act_clinic_id:
        clinic = db.query(Clinic).filter(Clinic.id == act_clinic_id).first()
        allowed = clinic and (
            user.is_platform_admin or
            (user.organization_id and clinic.organization_id == user.organization_id)
        )
        if allowed:
            # Detach so the in-memory scope override is never persisted to the DB.
            db.expunge(user)
            user.clinic_id = clinic.id
            # Above-clinic roles have no meaning to the clinic-level RoleCheckers,
            # so map them onto the clinic role they stand in for. Without this a
            # platform admin stepping into a clinic would be refused by every
            # owner-gated endpoint.
            if user.role in ABOVE_CLINIC_ROLES:
                user.role = ROLE_OWNER
    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    # A suspended clinic blocks its staff (platform admins are exempt).
    if current_user.clinic_id and not current_user.is_platform_admin:
        clinic = db.query(Clinic).filter(Clinic.id == current_user.clinic_id).first()
        if clinic and clinic.is_active is False:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Phòng khám đang tạm ngưng dịch vụ. Vui lòng liên hệ nhà cung cấp CareDesk AI."
            )
    return current_user


def get_platform_admin(current_user: User = Depends(get_current_active_user)) -> User:
    """Vendor/publisher super-admin: manages every tenant across the platform."""
    if not current_user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ Quản trị Nền tảng (nhà phát hành) mới có quyền truy cập khu vực này."
        )
    return current_user


def get_org_user(current_user: User = Depends(get_current_active_user)) -> User:
    """Chain owner: sees every clinic under their organization."""
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản của bạn không thuộc chuỗi/tổ chức nào."
        )
    return current_user


class RoleChecker:
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: User = Depends(get_current_active_user)) -> User:
        if current_user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Quyền truy cập bị từ chối: Tài khoản của bạn không có đủ quyền thực hiện hành động này."
            )
        return current_user

# Global dependency helpers for RBAC
verify_owner = RoleChecker([ROLE_OWNER])
verify_receptionist_or_above = RoleChecker([ROLE_RECEPTIONIST, ROLE_OWNER])
