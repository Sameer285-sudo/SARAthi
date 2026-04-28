"""FastAPI dependency injection for JWT auth and RBAC."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .jwt_handler import TokenPayload, decode_token
from .rbac import UserRole, get_level, has_permission

_bearer = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    user_id:     str
    username:    str
    role:        UserRole
    full_name:   str
    state_id:    Optional[str] = None
    district_id: Optional[str] = None
    mandal_id:   Optional[str] = None
    fps_id:      Optional[str] = None

    # --- convenience helpers ---

    def has_permission(self, permission: str) -> bool:
        return has_permission(self.role, permission)

    def level(self) -> int:
        return get_level(self.role)

    def is_admin(self) -> bool:
        return self.level() <= 2

    def scope_filter(self) -> dict:
        """Return the narrowest non-None scope IDs for DB query filtering."""
        f: dict = {}
        if self.fps_id:
            f["fps_id"] = self.fps_id
        elif self.mandal_id:
            f["mandal_id"] = self.mandal_id
        elif self.district_id:
            f["district_id"] = self.district_id
        elif self.state_id:
            f["state_id"] = self.state_id
        return f


def _token_payload(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> TokenPayload:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        return decode_token(creds.credentials)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


def get_current_user(payload: TokenPayload = Depends(_token_payload)) -> CurrentUser:
    return CurrentUser(
        user_id=payload.sub,
        username=payload.username,
        role=UserRole(payload.role),
        full_name=payload.full_name,
        state_id=payload.state_id,
        district_id=payload.district_id,
        mandal_id=payload.mandal_id,
        fps_id=payload.fps_id,
    )


def optional_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[CurrentUser]:
    """Returns CurrentUser if a valid token is present, None otherwise (unauthenticated = full access in dev)."""
    if creds is None:
        return None
    try:
        payload = decode_token(creds.credentials)
        return CurrentUser(
            user_id=payload.sub,
            username=payload.username,
            role=UserRole(payload.role),
            full_name=payload.full_name,
            state_id=payload.state_id,
            district_id=payload.district_id,
            mandal_id=payload.mandal_id,
            fps_id=payload.fps_id,
        )
    except Exception:
        return None


def require_roles(*roles: UserRole):
    """Dependency factory — returns a callable for use in Depends(require_roles(...))."""
    allowed = set(roles)

    def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return _check


def require_permission(permission: str):
    """Dependency factory — returns a callable for use in Depends(require_permission(...))."""
    def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_permission(permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing permission: {permission}")
        return user

    return _check


def require_min_level(level: int):
    """Dependency factory — returns a callable for use in Depends(require_min_level(...))."""
    def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.level() > level:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient access level")
        return user

    return _check
