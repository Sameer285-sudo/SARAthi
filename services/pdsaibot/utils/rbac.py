"""
Role-Based Access Control for PDSAI-Bot.
Controls which intents and data each role can access.
"""
from __future__ import annotations

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        "greeting", "farewell", "help",
        "stock_check", "anomaly_check", "demand_prediction",
        "allocation_recommendation", "delivery_status",
        "grievance", "general_query",
        "entitlement_query", "beneficiary_lookup",
        "distribution_schedule", "fps_location",
        "compliance_check", "complaint_fraud",
    },
    "field_staff": {
        "greeting", "farewell", "help",
        "stock_check", "delivery_status",
        "anomaly_check", "grievance", "general_query",
        "distribution_schedule", "compliance_check",
        "complaint_fraud", "beneficiary_lookup",
    },
    "citizen": {
        "greeting", "farewell", "help",
        "stock_check", "delivery_status",
        "grievance", "general_query",
        "entitlement_query", "distribution_schedule",
        "fps_location", "complaint_fraud",
    },
}

# Intents that always route to LangChain (complex multi-step reasoning)
LANGCHAIN_INTENTS: set[str] = {
    "demand_prediction",
    "allocation_recommendation",
    "anomaly_check",
    "compliance_check",
}

# Below this confidence → forward to LangChain for better handling
LANGCHAIN_CONFIDENCE_THRESHOLD = 0.42

ROLE_LABELS = {
    "admin":       "Administrator",
    "field_staff": "Field Staff",
    "citizen":     "Citizen",
}


def can_access(role: str, intent: str) -> bool:
    allowed = ROLE_PERMISSIONS.get(role, ROLE_PERMISSIONS["citizen"])
    return intent in allowed


def should_use_langchain(_role: str, intent: str, confidence: float) -> bool:
    if intent in LANGCHAIN_INTENTS:
        return True
    if confidence < LANGCHAIN_CONFIDENCE_THRESHOLD:
        return True
    return False


def denied_response(role: str, intent: str) -> str:
    return (
        f"Sorry, {ROLE_LABELS.get(role, role)} accounts do not have access to "
        f"{intent.replace('_', ' ')} information. "
        "Please contact your administrator if you need this data."
    )
