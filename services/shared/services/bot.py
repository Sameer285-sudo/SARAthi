from __future__ import annotations

import re

from sqlalchemy.orm import Session

from shared.schemas import BotQueryResponse
from shared.services.anomaly import get_alerts, get_summary as get_anomaly_summary
from shared.services.call_centre import get_summary as get_call_summary, get_tickets
from shared.services.smart_allot import get_summary as get_smart_allot_summary
from shared.services.smart_allot_ml import get_filter_metadata, get_model_info, get_recommendations

ROLE_LABELS = {"admin": "Administrator", "citizen": "Citizen", "field_staff": "Field Staff"}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def extract_entities(query: str) -> dict[str, str | int | None]:
    normalized = normalize(query)
    filters = get_filter_metadata()
    district_name = next((n for n in filters.district_names if n.lower() in normalized), None)
    item_name = next((i for i in filters.items if i.lower() in normalized), None)
    m = re.search(r"\b(?:district\s*code|code)\s*(\d{3,6})\b", normalized)
    return {"district_name": district_name, "district_code": int(m.group(1)) if m else None, "item_name": item_name}


def build_stock_response(db: Session, role: str, entities: dict) -> BotQueryResponse:
    recommendations = get_recommendations(
        district_name=entities["district_name"] if isinstance(entities["district_name"], str) else None,
        district_code=entities["district_code"] if isinstance(entities["district_code"], int) else None,
        item_name=entities["item_name"] if isinstance(entities["item_name"], str) else None,
    )
    summary = get_smart_allot_summary(db)
    model_info = get_model_info()
    if recommendations:
        top = recommendations[0]
        answer = (f"For {top.district_name}{' and ' + top.item_name if top.item_name else ''}, the predicted demand "
                  f"for {top.forecast_for_month} is {top.forecast_next_month:.2f} with a recommended allotment of {top.recommended_allotment:.2f}.")
        insights = [
            f"Last month distributed quantity: {top.last_month_distributed:.2f}",
            f"Last month allocated quantity: {top.last_month_allocated:.2f}",
            f"Safety stock recommendation: {top.safety_stock:.2f}",
            f"Model WAPE on validation/test split: {model_info.metrics.wape_percent:.2f}%",
        ]
    else:
        answer = (f"I could not find a matching SMARTAllot record. Overall view covers {summary.total_fps} district-item forecasts.")
        insights = [f"Total forecast: {summary.total_forecast}", f"Total recommended allotment: {summary.total_recommended_allotment}"]
    return BotQueryResponse(role=role, intent="smart_allot_query", answer=answer, detected_entities=entities,
                            insights=insights, suggestions=["Ask: Show Rice forecast for Guntur",
                                                             "Ask: What is the recommended allotment for district code 506"])


def build_anomaly_response(db: Session, role: str, entities: dict) -> BotQueryResponse:
    summary = get_anomaly_summary(db)
    alerts = [a for a in get_alerts(db) if a.anomaly_detected]
    top = max(alerts, key=lambda a: a.risk_score, default=None)
    answer = f"There are {summary.flagged_shipments} flagged shipments with {summary.open_investigation_queue} active investigations."
    insights = []
    if top:
        insights = [f"Top alert: {top.shipment_id} for {top.fps_id}", f"Severity: {top.severity}",
                    f"Reason: {top.reasons[0] if top.reasons else 'N/A'}"]
    return BotQueryResponse(role=role, intent="anomaly_summary", answer=answer, detected_entities=entities,
                            insights=insights, suggestions=["Ask: Show stock forecast for Guntur",
                                                             "Ask: How many high priority complaints are open"])


def build_grievance_response(db: Session, role: str, entities: dict) -> BotQueryResponse:
    summary = get_call_summary(db)
    tickets = get_tickets(db)
    high_priority = [t for t in tickets if t.priority == "HIGH"]
    answer = ("I can help with grievance support. Please share your district, FPS details, and a short issue summary." if role == "citizen"
              else f"The service desk currently has {summary.open_tickets} open complaints, including {summary.high_priority_tickets} high-priority tickets.")
    insights = [f"Languages covered: {', '.join(summary.languages_covered)}"]
    if high_priority:
        insights.append(f"Top urgent complaint category: {high_priority[0].category}")
    return BotQueryResponse(role=role, intent="grievance_support", answer=answer, detected_entities=entities,
                            insights=insights, suggestions=["Ask: Show complaint summary", "Ask: Guide me to register a grievance"])


def build_fallback(role: str, entities: dict) -> BotQueryResponse:
    return BotQueryResponse(
        role=role, intent="fallback",
        answer=f"{ROLE_LABELS.get(role, role)} support is available. I can answer stock forecasts, anomaly alerts, and grievance status questions.",
        detected_entities=entities,
        insights=["Data includes SMARTAllot forecasts, anomaly monitoring, and call-centre summaries."],
        suggestions=["Ask: Show Rice forecast for Guntur", "Ask: What anomalies need attention today",
                     "Ask: Help me with grievance support"],
    )


def answer_query(db: Session, query: str, role: str = "citizen", language: str = "English") -> BotQueryResponse:
    text = normalize(query)
    entities = extract_entities(query)
    if any(kw in text for kw in ["stock", "allot", "forecast", "rice", "wheat", "grain", "fortified"]):
        resp = build_stock_response(db, role, entities)
    elif any(kw in text for kw in ["anomaly", "anomalies", "alert", "alerts", "delay", "shipment", "deviation"]):
        resp = build_anomaly_response(db, role, entities)
    elif any(kw in text for kw in ["call", "ticket", "complaint", "grievance", "entitlement", "support"]):
        resp = build_grievance_response(db, role, entities)
    else:
        resp = build_fallback(role, entities)
    resp.language = language
    return resp
