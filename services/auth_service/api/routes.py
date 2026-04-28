"""Auth service REST endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from shared.auth.dependencies import CurrentUser, get_current_user, require_min_level
from shared.auth.jwt_handler import token_from_user
from shared.auth.password import hash_password, verify_password
from shared.auth.rbac import ROLE_DESCRIPTIONS, UserRole
from shared.db import get_db
from shared.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Pydantic schemas ────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    user_id:     str
    username:    str
    email:       str
    full_name:   str
    role:        str
    state_id:    Optional[str]
    district_id: Optional[str]
    mandal_id:   Optional[str]
    fps_id:      Optional[str]
    is_active:   bool

    class Config:
        from_attributes = True


class RegisterRequest(BaseModel):
    username:    str
    email:       str
    password:    str
    full_name:   str
    role:        UserRole
    state_id:    Optional[str] = None
    district_id: Optional[str] = None
    mandal_id:   Optional[str] = None
    fps_id:      Optional[str] = None
    ration_card_id: Optional[str] = None


class UpdateUserRequest(BaseModel):
    full_name:   Optional[str] = None
    role:        Optional[UserRole] = None
    is_active:   Optional[bool] = None
    state_id:    Optional[str] = None
    district_id: Optional[str] = None
    mandal_id:   Optional[str] = None
    fps_id:      Optional[str] = None


LoginResponse.model_rebuild()


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
    user.last_login = datetime.utcnow()
    db.commit()
    token = token_from_user(user)
    return LoginResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.user_id == current.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut.model_validate(user)


@router.post("/register", response_model=UserOut, status_code=201)
def register(
    req: RegisterRequest,
    _: CurrentUser = Depends(require_min_level(2)),  # district admin+
    db: Session = Depends(get_db),
):
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=409, detail="Username already exists")
    if db.query(User).filter(User.email == req.email).first():
        raise HTTPException(status_code=409, detail="Email already exists")

    user = User(
        user_id=str(uuid.uuid4()),
        username=req.username,
        email=req.email,
        hashed_password=hash_password(req.password),
        full_name=req.full_name,
        role=req.role.value,
        state_id=req.state_id,
        district_id=req.district_id,
        mandal_id=req.mandal_id,
        fps_id=req.fps_id,
        ration_card_id=req.ration_card_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.get("/users", response_model=list[UserOut])
def list_users(
    role: Optional[str] = None,
    _: CurrentUser = Depends(require_min_level(2)),
    db: Session = Depends(get_db),
):
    q = db.query(User)
    if role:
        q = q.filter(User.role == role)
    return [UserOut.model_validate(u) for u in q.all()]


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    req: UpdateUserRequest,
    _: CurrentUser = Depends(require_min_level(2)),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    for field, value in req.model_dump(exclude_none=True).items():
        if field == "role":
            setattr(user, field, value.value if isinstance(value, UserRole) else value)
        else:
            setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.get("/roles")
def list_roles():
    return [
        {
            "role": role.value,
            "level": level,
            **ROLE_DESCRIPTIONS[role],
        }
        for role, level in [
            (UserRole.STATE_ADMIN, 1),
            (UserRole.DISTRICT_ADMIN, 2),
            (UserRole.MANDAL_ADMIN, 3),
            (UserRole.AFSO, 4),
            (UserRole.FPS_DEALER, 5),
            (UserRole.RATION_CARD_HOLDER, 6),
        ]
    ]
