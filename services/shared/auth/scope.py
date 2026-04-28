"""
Translates a CurrentUser's scope into SQLAlchemy filter kwargs
for each model type used across services.

Usage:
    from shared.auth.scope import scope_for_fps, scope_for_tickets, scope_for_movement

    q = db.query(FPSStockMetric)
    filters = scope_for_fps(user)   # e.g. {"district": "Guntur"}
    for col, val in filters.items():
        q = q.filter(getattr(FPSStockMetric, col) == val)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from shared.auth.dependencies import CurrentUser


def scope_for_fps(user: Optional["CurrentUser"]) -> dict:
    """Filter kwargs for FPSStockMetric (columns: fps_id, mandal, district)."""
    if user is None:
        return {}
    if user.fps_id:
        return {"fps_id": user.fps_id}
    if user.mandal_id:
        return {"mandal": user.mandal_id}
    if user.district_id:
        return {"district": user.district_id}
    return {}


def scope_for_movement(user: Optional["CurrentUser"]) -> dict:
    """Filter kwargs for MovementRecord (columns: fps_id)."""
    if user is None:
        return {}
    if user.fps_id:
        return {"fps_id": user.fps_id}
    return {}


def scope_for_tickets(user: Optional["CurrentUser"]) -> dict:
    """Filter kwargs for GrievanceTicket (columns: district_name, fps_reference)."""
    if user is None:
        return {}
    if user.fps_id:
        return {"fps_reference": user.fps_id}
    if user.district_id:
        return {"district_name": user.district_id}
    return {}
