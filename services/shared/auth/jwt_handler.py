"""JWT creation and verification for PDS360."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from pydantic import BaseModel

SECRET_KEY  = os.getenv("JWT_SECRET_KEY", "pds360-dev-secret-change-in-production")
ALGORITHM   = "HS256"
EXPIRE_MINS = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))  # 8 hours default


class TokenPayload(BaseModel):
    sub:         str               # user_id
    username:    str
    role:        str
    full_name:   str
    state_id:    str | None = None
    district_id: str | None = None
    mandal_id:   str | None = None
    fps_id:      str | None = None
    exp:         int | None = None


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    payload = data.copy()
    expire  = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=EXPIRE_MINS))
    payload["exp"] = expire
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> TokenPayload:
    """Decode and validate a JWT. Raises JWTError on failure."""
    raw = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    return TokenPayload(**raw)


def token_from_user(user: Any) -> str:
    """Shortcut: build token directly from a User ORM row."""
    return create_access_token({
        "sub":         user.user_id,
        "username":    user.username,
        "role":        user.role,
        "full_name":   user.full_name,
        "state_id":    user.state_id,
        "district_id": user.district_id,
        "mandal_id":   user.mandal_id,
        "fps_id":      user.fps_id,
    })
