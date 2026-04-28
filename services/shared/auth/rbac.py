"""
RBAC definitions for PDS360.

Hierarchy (1 = most powerful):
  1. STATE_ADMIN
  2. DISTRICT_ADMIN
  3. MANDAL_ADMIN
  4. AFSO
  5. FPS_DEALER
  6. RATION_CARD_HOLDER
"""
from __future__ import annotations

from enum import Enum


class UserRole(str, Enum):
    STATE_ADMIN        = "STATE_ADMIN"
    DISTRICT_ADMIN     = "DISTRICT_ADMIN"
    MANDAL_ADMIN       = "MANDAL_ADMIN"
    AFSO               = "AFSO"
    FPS_DEALER         = "FPS_DEALER"
    RATION_CARD_HOLDER = "RATION_CARD_HOLDER"


ROLE_LEVEL: dict[UserRole, int] = {
    UserRole.STATE_ADMIN:        1,
    UserRole.DISTRICT_ADMIN:     2,
    UserRole.MANDAL_ADMIN:       3,
    UserRole.AFSO:               4,
    UserRole.FPS_DEALER:         5,
    UserRole.RATION_CARD_HOLDER: 6,
}

ROLE_PERMISSIONS: dict[UserRole, set[str]] = {
    UserRole.STATE_ADMIN: {
        "analytics:global", "analytics:district",
        "anomalies:all",
        "stock:all",
        "tickets:all", "tickets:manage",
        "call_centre:all",
        "allocations:approve", "allocations:view",
        "users:manage",
        "bot:admin_insights",
        "reports:all",
        "fps:all",
    },
    UserRole.DISTRICT_ADMIN: {
        "analytics:district",
        "anomalies:district",
        "stock:district",
        "tickets:district", "tickets:manage",
        "call_centre:district",
        "allocations:view",
        "bot:admin_insights",
        "reports:district",
        "fps:district",
    },
    UserRole.MANDAL_ADMIN: {
        "analytics:mandal",
        "anomalies:mandal",
        "stock:mandal",
        "tickets:mandal", "tickets:escalate",
        "deliveries:track",
        "bot:staff_insights",
        "fps:mandal",
    },
    UserRole.AFSO: {
        "analytics:mandal",
        "anomalies:mandal",
        "stock:verify",
        "fps:monitor",
        "reports:approve",
        "deliveries:track",
        "bot:staff_insights",
    },
    UserRole.FPS_DEALER: {
        "stock:update", "stock:view_own",
        "allocations:view_own",
        "transactions:manage",
        "complaints:respond",
        "beneficiaries:view",
        "bot:basic",
    },
    UserRole.RATION_CARD_HOLDER: {
        "entitlement:view",
        "deliveries:own",
        "complaints:create",
        "transactions:own",
        "bot:basic",
    },
}

# What each role sees in the chatbot — used by PDSAI-Bot router
CHATBOT_DETAIL_LEVEL: dict[UserRole, str] = {
    UserRole.STATE_ADMIN:        "full_analytics",
    UserRole.DISTRICT_ADMIN:     "district_analytics",
    UserRole.MANDAL_ADMIN:       "operational",
    UserRole.AFSO:               "operational",
    UserRole.FPS_DEALER:         "shop_level",
    UserRole.RATION_CARD_HOLDER: "personal",
}

# Roles allowed to call each API namespace
API_ROLE_MAP: dict[str, list[UserRole]] = {
    "analytics":  [UserRole.STATE_ADMIN, UserRole.DISTRICT_ADMIN],
    "anomalies":  [UserRole.STATE_ADMIN, UserRole.DISTRICT_ADMIN, UserRole.MANDAL_ADMIN, UserRole.AFSO],
    "stock":      [UserRole.STATE_ADMIN, UserRole.DISTRICT_ADMIN, UserRole.MANDAL_ADMIN, UserRole.AFSO, UserRole.FPS_DEALER],
    "tickets":    [UserRole.STATE_ADMIN, UserRole.DISTRICT_ADMIN, UserRole.MANDAL_ADMIN, UserRole.AFSO, UserRole.FPS_DEALER, UserRole.RATION_CARD_HOLDER],
    "allocations":[UserRole.STATE_ADMIN, UserRole.DISTRICT_ADMIN],
    "users":      [UserRole.STATE_ADMIN],
}


def has_permission(role: UserRole, permission: str) -> bool:
    perms = ROLE_PERMISSIONS.get(role, set())
    if permission in perms:
        return True
    ns = permission.split(":")[0]
    return f"{ns}:all" in perms


def get_level(role: UserRole) -> int:
    return ROLE_LEVEL.get(role, 99)


def is_admin(role: UserRole) -> bool:
    return get_level(role) <= 2


def roles_at_or_above(level: int) -> list[UserRole]:
    return [r for r, lvl in ROLE_LEVEL.items() if lvl <= level]


ROLE_DESCRIPTIONS: dict[UserRole, dict] = {
    UserRole.STATE_ADMIN: {
        "scope": "Entire state",
        "description": "Full visibility across all districts, mandals, and FPS units",
    },
    UserRole.DISTRICT_ADMIN: {
        "scope": "Assigned district",
        "description": "District-level analytics, anomaly monitoring, and ticket management",
    },
    UserRole.MANDAL_ADMIN: {
        "scope": "Assigned mandal",
        "description": "Mandal-level stock tracking, delivery monitoring, complaint escalation",
    },
    UserRole.AFSO: {
        "scope": "Operational supervision",
        "description": "FPS performance monitoring, stock verification, report approval",
    },
    UserRole.FPS_DEALER: {
        "scope": "Individual Fair Price Shop",
        "description": "Stock updates, allocation view, beneficiary management",
    },
    UserRole.RATION_CARD_HOLDER: {
        "scope": "Personal",
        "description": "Entitlement check, delivery tracking, complaint raising",
    },
}
