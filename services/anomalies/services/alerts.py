"""
Alert generation and management.
Creates alerts from detected anomalies and persists them to SQLite.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


_SEVERITY_MESSAGES = {
    "CRITICAL": "CRITICAL anomaly detected — immediate investigation required",
    "HIGH":     "High-severity anomaly detected — review recommended",
    "MEDIUM":   "Medium-severity anomaly — monitor closely",
    "LOW":      "Low-severity anomaly flagged for review",
}


def build_alerts(anomaly_results: list[dict]) -> list[dict]:
    """
    Given anomaly detection results, generate alert dicts
    for all records where is_anomaly=True.
    """
    alerts = []
    for rec in anomaly_results:
        if not rec.get("is_anomaly"):
            continue

        sev     = rec.get("severity", "LOW")
        reasons = rec.get("reasons", [])
        msg_base = _SEVERITY_MESSAGES.get(sev, "Anomaly detected")
        detail   = f" | {'; '.join(reasons)}" if reasons else ""

        alerts.append({
            "alert_id":       str(uuid.uuid4()),
            "transaction_id": rec["transaction_id"],
            "location":       rec["location"],
            "timestamp":      rec["timestamp"],
            "severity":       sev,
            "message":        msg_base + detail,
            "reasons":        reasons,
            "created_at":     _now(),
            "acknowledged":   False,
        })

    return alerts
