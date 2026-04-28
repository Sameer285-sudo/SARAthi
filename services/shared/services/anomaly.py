from sqlalchemy.orm import Session

from shared.models import MovementRecord
from shared.schemas import AnomalyAlert, AnomalySummary


def _clamp(value: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, value))


def evaluate_record(record: MovementRecord) -> AnomalyAlert:
    quantity_mismatch = record.dispatch_qty - record.delivered_qty
    delay_hours = max(record.actual_transit_hours - record.expected_transit_hours, 0)
    spike_delta = max(record.transaction_spike - 1.2, 0)
    risk_score = round(
        _clamp(quantity_mismatch / max(record.dispatch_qty, 1) + delay_hours / 24 + spike_delta, 0, 1), 2
    )
    reasons: list[str] = []
    if quantity_mismatch > 0:
        reasons.append(f"Delivered quantity is short by {quantity_mismatch} units.")
    if delay_hours > 0:
        reasons.append(f"Shipment delay detected: {delay_hours} hours beyond expected transit.")
    if record.transaction_spike > 1.2:
        reasons.append(f"Transaction volume spike detected at {round((record.transaction_spike - 1) * 100)}%.")
    severity = "HIGH" if risk_score >= 0.6 else "MEDIUM" if risk_score >= 0.3 else "LOW"
    return AnomalyAlert(
        shipment_id=record.shipment_id,
        fps_id=record.fps_id,
        risk_score=risk_score,
        severity=severity,
        quantity_mismatch=quantity_mismatch,
        delay_hours=delay_hours,
        transaction_spike=record.transaction_spike,
        anomaly_detected=bool(reasons),
        reasons=reasons,
    )


def get_alerts(db: Session) -> list[AnomalyAlert]:
    records = db.query(MovementRecord).order_by(MovementRecord.shipment_id).all()
    return [evaluate_record(r) for r in records]


def get_summary(db: Session) -> AnomalySummary:
    alerts = get_alerts(db)
    return AnomalySummary(
        total_shipments=len(alerts),
        flagged_shipments=sum(1 for a in alerts if a.anomaly_detected),
        high_severity=sum(1 for a in alerts if a.severity == "HIGH"),
        open_investigation_queue=sum(1 for a in alerts if a.risk_score >= 0.3),
    )
