from datetime import timedelta
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.core.security import create_access_token, verify_password, get_password_hash
from backend.app.api.deps import CLINIC_ROLES, ROLE_OWNER, get_current_active_user
from backend.app.models.models import User, Clinic
from backend.app.schemas.schemas import Token, UserOut, UserCreate, ClinicRegister
from backend.app.services.audit import log_action
from backend.app.services.rate_limit import register_rate_limiter

router = APIRouter()

@router.post("/login", response_model=Token)
def login_access_token(
    db: Session = Depends(get_db), form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """
    OAuth2 compatible token login, get an access token for future requests.
    """
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email hoặc mật khẩu không chính xác"
        )
    elif not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tài khoản đã bị vô hiệu hóa"
        )
    # Block staff of a suspended clinic (platform admins are exempt)
    if user.clinic_id and not user.is_platform_admin:
        clinic = db.query(Clinic).filter(Clinic.id == user.clinic_id).first()
        if clinic and clinic.is_active is False:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Phòng khám đang tạm ngưng dịch vụ. Vui lòng liên hệ nhà cung cấp CareDesk AI."
            )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    log_action(db, user.id, "login", f"Đăng nhập: {user.email}")
    db.commit()
    return {
        "access_token": create_access_token(
            user.email, expires_delta=access_token_expires
        ),
        "token_type": "bearer",
    }


@router.post("/register-clinic", response_model=Token, dependencies=[Depends(register_rate_limiter)])
def register_clinic(
    *,
    db: Session = Depends(get_db),
    reg_in: ClinicRegister
) -> Any:
    """
    SaaS self-service signup: creates a new Clinic (Free plan) + its Owner account.
    Global AI safety rules automatically apply to the new tenant.
    """
    existing = db.query(User).filter(User.email == reg_in.email).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Email này đã được đăng ký sử dụng trong hệ thống."
        )

    clinic = Clinic(
        name=reg_in.clinic_name,
        phone=reg_in.phone,
        address=reg_in.address,
        plan="free",
        ai_quota_monthly=settings.PLAN_FREE_QUOTA
    )
    db.add(clinic)
    db.flush()  # get clinic.id

    owner = User(
        clinic_id=clinic.id,
        email=reg_in.email,
        password_hash=get_password_hash(reg_in.password),
        full_name=reg_in.owner_name,
        role="owner",
        is_active=True
    )
    db.add(owner)
    db.flush()
    log_action(db, owner.id, "register_clinic", f"Đăng ký phòng khám mới: {clinic.name} (gói Free)")
    db.commit()

    # Every new tenant starts with the default revenue automations enabled
    from backend.app.services.events import seed_default_automations
    seed_default_automations(db, clinic.id)

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return {
        "access_token": create_access_token(owner.email, expires_delta=access_token_expires),
        "token_type": "bearer",
    }


@router.get("/me", response_model=UserOut)
def read_user_me(
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """
    Get current user info.
    """
    return current_user


@router.post("/register-admin-only", response_model=UserOut)
def create_user_by_admin(
    *,
    db: Session = Depends(get_db),
    user_in: UserCreate,
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """
    Create a staff account inside the caller's own clinic. Owner only.
    """
    if current_user.role != ROLE_OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ chủ phòng khám mới có quyền tạo tài khoản nhân viên."
        )

    # The role arrives from the client, so it must be checked against the set of
    # roles that exist *inside* a clinic. Otherwise an owner could hand out
    # "org_owner" or "platform" and grant themselves the whole chain.
    if user_in.role not in CLINIC_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Vai trò không hợp lệ. Chỉ chấp nhận: {', '.join(CLINIC_ROLES)}."
        )

    user = db.query(User).filter(User.email == user_in.email).first()
    if user:
        raise HTTPException(
            status_code=400,
            detail="Email này đã được đăng ký sử dụng trong hệ thống."
        )

    db_obj = User(
        clinic_id=current_user.clinic_id,
        email=user_in.email,
        password_hash=get_password_hash(user_in.password),
        full_name=user_in.full_name,
        role=user_in.role,
        is_active=True
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj
