"""
PDSAI-Bot HTTP client for the Call Centre.

Forwards citizen queries to the PDSAI-Bot service (port 8004) and returns
structured responses including intent, suggestions, and data.

Falls back gracefully if PDSAI-Bot is unreachable.
"""
from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger(__name__)

_BOT_URL = os.getenv("PDSAIBOT_URL", "http://localhost:8004")
_TIMEOUT = 10.0


def _post(path: str, body: dict) -> dict:
    try:
        r = httpx.post(f"{_BOT_URL}{path}", json=body, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        log.warning("PDSAI-Bot unreachable at %s%s: %s", _BOT_URL, path, exc)
        return {}


def send_message(
    message: str,
    role: str = "citizen",
    session_id: str | None = None,
    user_id: str = "call-centre",
    language: str = "English",
) -> dict:
    """
    Forward a message to PDSAI-Bot /api/bot/chat.

    Returns the full ChatResponse dict, or a fallback dict if unavailable.
    Keys: response, intent, intent_confidence, source, data, insights, suggestions, session_id
    """
    body = {
        "message":    message,
        "role":       role,
        "session_id": session_id,
        "user_id":    user_id,
        "language":   language,
    }
    result = _post("/api/bot/chat", body)
    if not result:
        return _fallback_response(message)
    return result


def _fallback_response(message: str) -> dict:
    """Structured fallback when PDSAI-Bot is offline."""
    lower = message.lower()
    if any(w in lower for w in ["stock", "rice", "wheat"]):
        intent, response = "stock_check", "Stock information is currently unavailable. Please try again shortly."
    elif any(w in lower for w in ["anomal", "alert", "fraud"]):
        intent, response = "anomaly_check", "Anomaly data is currently unavailable."
    elif any(w in lower for w in ["complaint", "grievance"]):
        intent, response = "grievance", "Your grievance will be registered. A ticket is being created."
    else:
        intent, response = "general_query", "Thank you for contacting PDS360. A support agent will assist you shortly."
    return {
        "response":          response,
        "intent":            intent,
        "intent_confidence": 0.50,
        "source":            "call_centre_fallback",
        "data":              {},
        "insights":          [],
        "suggestions":       [],
        "session_id":        None,
    }


def get_bot_health() -> dict:
    """Check PDSAI-Bot health status."""
    try:
        r = httpx.get(f"{_BOT_URL}/health", timeout=3.0)
        return r.json()
    except Exception:
        return {"status": "unreachable", "service": "pdsaibot"}
