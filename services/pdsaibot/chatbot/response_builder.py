"""
Formats raw NLU + data into structured ChatResponse objects.
Also builds intent-specific suggestions and insights.
"""
from __future__ import annotations

from models.schemas import ChatResponse

_SUGGESTIONS: dict[str, list[str]] = {
    "stock_check": [
        "Ask: Predict demand for Fine Rice next 3 months",
        "Ask: Show allocation recommendations",
        "Ask: Are there any anomalies in Chittoor?",
    ],
    "anomaly_check": [
        "Ask: Show CRITICAL anomalies only",
        "Ask: What is the delivery status for a flagged transaction?",
        "Ask: Give me the compliance report for the district",
    ],
    "demand_prediction": [
        "Ask: Show stock allocation recommendations",
        "Ask: What is the current stock level for Fine Rice?",
        "Ask: Predict demand for Atta in Chittoor",
    ],
    "allocation_recommendation": [
        "Ask: What is the forecasted demand next month?",
        "Ask: Show anomalies in high-risk locations",
        "Ask: Stock status for Annamayya",
    ],
    "delivery_status": [
        "Ask: Are there any delivery anomalies?",
        "Ask: Show all delayed shipments",
        "Ask: Check stock levels in Chittoor",
    ],
    "grievance": [
        "Ask: How many complaints are currently open?",
        "Ask: What is the grievance resolution time?",
        "Ask: File a complaint about short supply",
    ],
    "entitlement_query": [
        "Ask: When is the next distribution date?",
        "Ask: Where is my nearest FPS shop?",
        "Ask: How do I file a grievance?",
    ],
    "beneficiary_lookup": [
        "Ask: What is my monthly entitlement?",
        "Ask: File a grievance about my ration card",
        "Ask: Where is my FPS shop?",
    ],
    "distribution_schedule": [
        "Ask: What is my monthly ration entitlement?",
        "Ask: Where is my FPS shop?",
        "Ask: How do I file a complaint if distribution is missed?",
    ],
    "fps_location": [
        "Ask: When is the next distribution?",
        "Ask: What is my monthly rice entitlement?",
        "Ask: How do I file a complaint about my FPS?",
    ],
    "compliance_check": [
        "Ask: Show CRITICAL anomalies in the district",
        "Ask: How many high-severity shipments are flagged?",
        "Ask: Export the compliance audit report",
    ],
    "complaint_fraud": [
        "Ask: File a formal grievance",
        "Ask: Show anomalies related to this location",
        "Ask: What is the status of my complaint?",
    ],
    "general_query": [
        "Ask: Show stock levels in Annamayya",
        "Ask: What anomalies occurred today?",
        "Ask: Predict next month demand for Fine Rice",
    ],
    "greeting": [
        "Try: What is my monthly rice entitlement?",
        "Try: Show stock levels in Chittoor",
        "Try: Are there any CRITICAL anomalies?",
    ],
    "help": [
        "Ask: Show stock levels in Annamayya",
        "Ask: Predict demand for Fine Rice next 3 months",
        "Ask: Are there any anomalies today?",
    ],
    "farewell": [],
}

_INSIGHTS: dict[str, list[str]] = {
    "stock_check":               ["Stock data from GradientBoosting ML (MAE 44.1 kg, WAPE 3.9%)"],
    "anomaly_check":             ["Detection uses IsolationForest + Z-score + rule-based checks"],
    "demand_prediction":         ["GradientBoosting forecast with lag, rolling-mean, and seasonal features"],
    "allocation_recommendation": ["LP-optimised via HiGHS solver with shortage/overstock constraints"],
    "delivery_status":           ["Real-time tracking via the Anomaly Detection service"],
    "grievance":                 ["Tickets routed to AI Call Centre with SLA tracking (48h resolution)"],
    "entitlement_query":         ["Entitlements governed by NFSA 2013 and AP Civil Supplies rules"],
    "beneficiary_lookup":        ["Beneficiary records linked to Aadhaar via ePoS authentication"],
    "distribution_schedule":     ["Distribution schedule set by AP Civil Supplies Corporation"],
    "fps_location":              ["FPS network managed by AP Civil Supplies with ~20,000 shops statewide"],
    "compliance_check":          ["Compliance KPIs: anomaly rate <10% compliant, >20% requires action"],
    "complaint_fraud":           ["Fraud reports escalated to Vigilance Cell within 24 hours"],
    "general_query":             ["Aggregated from SMARTAllot, Anomaly Detection, and Call Centre services"],
}


def build_response(
    *,
    session_id:     str,
    user_id:        str,
    role:           str,
    message:        str,
    nlu_intent:     str,
    nlu_confidence: float,
    nlu_source:     str,
    response_text:  str,
    agent_source:   str,
    data:           dict,
    language:       str = "English",
) -> ChatResponse:
    suggestions = _SUGGESTIONS.get(nlu_intent, _SUGGESTIONS["general_query"])
    insights    = list(_INSIGHTS.get(nlu_intent, []))

    _enrich_insights(nlu_intent, data, insights)

    return ChatResponse(
        session_id=session_id,
        user_id=user_id,
        role=role,
        message=message,
        response=response_text,
        intent=nlu_intent,
        intent_confidence=round(nlu_confidence, 4),
        source=f"{nlu_source}+{agent_source}" if agent_source != nlu_source else nlu_source,
        data=data,
        insights=insights[:4],
        suggestions=suggestions[:3],
        language=language,
    )


def _enrich_insights(intent: str, data: dict, insights: list[str]) -> None:
    """Append data-driven insights based on live values."""
    if intent == "anomaly_check":
        summary = data.get("summary", {})
        rate = summary.get("anomaly_rate_pct", None)
        if rate is not None:
            if rate > 20:
                insights.append(f"Anomaly rate {rate:.1f}% exceeds 20% action threshold")
            elif rate > 10:
                insights.append(f"Anomaly rate {rate:.1f}% — moderate risk, monitor closely")
            else:
                insights.append(f"Anomaly rate {rate:.1f}% — within acceptable range")

    elif intent in ("demand_prediction", "stock_check"):
        recs = data.get("recommendations", [])
        if recs:
            total_f = sum(r.get("forecast_next_month", 0) for r in recs)
            total_a = sum(r.get("recommended_allotment", 0) for r in recs)
            if total_f > 0:
                buffer_pct = ((total_a - total_f) / total_f) * 100
                insights.append(f"Safety buffer: {buffer_pct:.1f}% above forecast demand")

    elif intent == "allocation_recommendation":
        summary = data.get("summary", {})
        shortage = summary.get("avg_shortage_risk_pct", None)
        if shortage is not None and shortage > 15:
            insights.append(f"High shortage risk ({shortage:.1f}%) — consider increasing supply")

    elif intent == "compliance_check":
        summary = data.get("summary", {})
        rate = summary.get("anomaly_rate_pct", None)
        if rate is not None:
            status = "COMPLIANT" if rate < 10 else ("MONITOR" if rate < 20 else "ACTION REQUIRED")
            insights.append(f"Compliance status: {status} (anomaly rate {rate:.1f}%)")
