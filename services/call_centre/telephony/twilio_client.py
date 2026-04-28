"""
Twilio client wrapper for PDS Call Centre IVR.

Responsibilities
----------------
- Call session memory  : track language + context per CallSid
- Signature validation : verify webhook requests are from Twilio
- REST client factory  : return configured twilio.rest.Client
- Config probe         : report which env vars are set
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

_SESSION_TTL = 3600  # seconds
_SESSIONS: dict[str, "CallSession"] = {}


# ── Call session ──────────────────────────────────────────────────────────────

@dataclass
class CallSession:
    call_sid:   str
    language:   str   = "English"
    session_id: str   = field(default_factory=lambda: str(uuid.uuid4()))
    turn_count: int   = 0
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    transcript: list[dict] = field(default_factory=list)

    def touch(self) -> None:
        self.last_active = time.time()
        self.turn_count += 1


def get_session(call_sid: str) -> CallSession:
    _evict_stale()
    if call_sid not in _SESSIONS:
        _SESSIONS[call_sid] = CallSession(call_sid=call_sid)
        log.info("New IVR session: %s", call_sid)
    return _SESSIONS[call_sid]


def set_language(call_sid: str, language: str) -> CallSession:
    session = get_session(call_sid)
    session.language = language
    session.touch()
    log.info("Language set: call=%s lang=%s", call_sid, language)
    return session


def end_session(call_sid: str) -> CallSession | None:
    session = _SESSIONS.pop(call_sid, None)
    if session:
        log.info("Session ended: call=%s turns=%d lang=%s", call_sid, session.turn_count, session.language)
    return session


def _evict_stale() -> None:
    now = time.time()
    stale = [k for k, v in _SESSIONS.items() if now - v.last_active > _SESSION_TTL]
    for k in stale:
        del _SESSIONS[k]


def active_sessions() -> int:
    _evict_stale()
    return len(_SESSIONS)


# ── Twilio SDK helpers ────────────────────────────────────────────────────────

def get_twilio_client():
    """Return a configured Twilio REST client, or None if credentials are missing."""
    sid   = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    if not sid or not token:
        log.warning("Twilio credentials not configured — IVR outbound calls disabled")
        return None
    try:
        from twilio.rest import Client
        return Client(sid, token)
    except Exception as exc:
        log.error("Failed to create Twilio client: %s", exc)
        return None


def validate_signature(request_url: str, post_params: dict, signature: str) -> bool:
    """
    Verify that a webhook request came from Twilio.
    Returns True in dev mode (no AUTH_TOKEN set).
    """
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    if not token:
        return True  # dev mode — skip validation
    try:
        from twilio.request_validator import RequestValidator
        return RequestValidator(token).validate(request_url, post_params, signature)
    except Exception as exc:
        log.error("Signature validation error: %s", exc)
        return False


def is_configured() -> bool:
    return bool(os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("TWILIO_AUTH_TOKEN"))


def config_status() -> dict:
    return {
        "configured":       is_configured(),
        "account_sid_set":  bool(os.getenv("TWILIO_ACCOUNT_SID")),
        "auth_token_set":   bool(os.getenv("TWILIO_AUTH_TOKEN")),
        "phone_number":     os.getenv("TWILIO_PHONE_NUMBER", ""),
        "public_base_url":  os.getenv("PUBLIC_BASE_URL", ""),
        "active_sessions":  active_sessions(),
    }
