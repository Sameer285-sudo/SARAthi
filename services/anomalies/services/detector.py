"""
Anomaly detection engine.

Three layers:
  1. Rule-based checks   — fast, interpretable thresholds
  2. Z-score             — statistical outliers per feature
  3. Isolation Forest    — ML-based, fits on accumulated data

Composite score = max(rule_score, zscore_score, if_score)
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────

DELAY_HIGH_HOURS     = 6.0     # > 6h delay is HIGH
DELAY_CRITICAL_HOURS = 24.0    # > 24h is CRITICAL
MISMATCH_HIGH_PCT    = 15.0    # > 15% mismatch is HIGH
MISMATCH_CRITICAL_PCT = 30.0   # > 30% is CRITICAL
ZSCORE_THRESHOLD     = 2.5
IF_CONTAMINATION     = 0.10    # expect ~10% anomalies
MIN_SAMPLES_FOR_IF   = 10      # need at least this many rows to fit IForest

FEATURE_COLS = ["delivery_delay_hours", "quantity_mismatch", "mismatch_pct", "stock_variation"]


# ── Detector class ────────────────────────────────────────────────────────────

class AnomalyEngine:
    """Stateful anomaly detector; fits IForest once enough data arrives."""

    def __init__(self) -> None:
        self._if_model = None
        self._if_fitted_on: int = 0   # sample count when last fitted

    # ── Public API ────────────────────────────────────────────────────────────

    def detect_batch(self, records: list[dict]) -> list[dict]:
        """
        Score a batch of preprocessed transaction dicts.
        Returns list of anomaly result dicts (one per record).
        """
        if not records:
            return []

        X = _build_feature_matrix(records)

        # Rule-based scores
        rule_results = [_rule_check(r) for r in records]

        # Z-score (computed over the batch, or a larger window if we store history)
        z_scores = _zscore_batch(X)

        # Isolation Forest
        if_scores = self._if_scores(X)

        results = []
        for i, rec in enumerate(records):
            rule = rule_results[i]
            z    = z_scores[i]
            ifscore = if_scores[i]

            # Composite anomaly score (0→1, higher = more anomalous)
            composite = max(rule["rule_score"], z, ifscore)

            # Determine primary type
            if rule["rule_score"] > 0.5:
                atype = "rule_based"
            elif ifscore > z:
                atype = "isolation_forest"
            else:
                atype = "zscore"

            # Severity
            severity = _severity(composite, rule)

            is_anomaly = composite > 0.3 or bool(rule["violations"])

            results.append({
                **rec,
                "isolation_score": round(ifscore, 4),
                "zscore_max":      round(z, 4),
                "anomaly_score":   round(composite, 4),
                "anomaly_type":    atype if is_anomaly else "none",
                "severity":        severity if is_anomaly else "LOW",
                "reasons":         rule["reasons"],
                "is_anomaly":      is_anomaly,
            })

        return results

    def maybe_refit(self, all_records: list[dict]) -> None:
        """Refit IsolationForest if we have enough new data."""
        n = len(all_records)
        if n < MIN_SAMPLES_FOR_IF:
            return
        if n <= self._if_fitted_on * 1.2 and self._if_model is not None:
            return  # no significant new data
        try:
            from sklearn.ensemble import IsolationForest
            X = _build_feature_matrix(all_records)
            model = IsolationForest(
                contamination=IF_CONTAMINATION,
                n_estimators=100,
                random_state=42,
                n_jobs=-1,
            )
            model.fit(X)
            self._if_model = model
            self._if_fitted_on = n
            log.info("IsolationForest fitted on %d samples", n)
        except Exception as exc:
            log.warning("IForest fit failed: %s", exc)

    # ── Private ───────────────────────────────────────────────────────────────

    def _if_scores(self, X: np.ndarray) -> list[float]:
        if self._if_model is None or X.shape[0] == 0:
            return [0.0] * X.shape[0]
        try:
            # decision_function: negative = more anomalous
            raw = self._if_model.decision_function(X)
            # Normalise to [0, 1] (higher = more anomalous)
            mn, mx = raw.min(), raw.max()
            if mx == mn:
                return [0.0] * len(raw)
            normed = 1.0 - (raw - mn) / (mx - mn)
            return [round(float(v), 4) for v in normed]
        except Exception:
            return [0.0] * X.shape[0]


# ── Feature matrix ────────────────────────────────────────────────────────────

def _build_feature_matrix(records: list[dict]) -> np.ndarray:
    rows = []
    for r in records:
        rows.append([
            float(r.get("delivery_delay_hours", 0) or 0),
            float(r.get("quantity_mismatch",    0) or 0),
            float(r.get("mismatch_pct",         0) or 0),
            float(r.get("stock_variation",      0) or 0),
        ])
    return np.array(rows, dtype=float)


# ── Z-score ───────────────────────────────────────────────────────────────────

def _zscore_batch(X: np.ndarray) -> list[float]:
    """Return per-row max absolute Z-score across features, normalised to [0,1]."""
    if X.shape[0] < 2:
        return [0.0] * X.shape[0]
    means = X.mean(axis=0)
    stds  = X.std(axis=0)
    stds[stds == 0] = 1.0
    Z = np.abs((X - means) / stds)
    max_z = Z.max(axis=1)
    # Normalise: z ≥ THRESHOLD maps to score ≥ 0.5
    scores = np.clip(max_z / (ZSCORE_THRESHOLD * 2), 0.0, 1.0)
    return [round(float(v), 4) for v in scores]


# ── Rule-based checks ─────────────────────────────────────────────────────────

def _rule_check(r: dict) -> dict:
    violations: list[str] = []
    rule_score = 0.0

    delay  = float(r.get("delivery_delay_hours", 0) or 0)
    mismatch_pct = float(r.get("mismatch_pct",  0) or 0)
    mismatch = float(r.get("quantity_mismatch", 0) or 0)
    sa     = float(r.get("stock_after",         0) or 0)
    sb     = float(r.get("stock_before",        0) or 0)

    # Negative stock after delivery
    if sa < 0:
        violations.append(f"Negative stock after delivery ({sa:.0f} units)")
        rule_score = max(rule_score, 1.0)

    # Delivery delay
    if delay > DELAY_CRITICAL_HOURS:
        violations.append(f"Critical delivery delay: {delay:.1f}h (>{DELAY_CRITICAL_HOURS}h)")
        rule_score = max(rule_score, 0.95)
    elif delay > DELAY_HIGH_HOURS:
        violations.append(f"High delivery delay: {delay:.1f}h (>{DELAY_HIGH_HOURS}h)")
        rule_score = max(rule_score, 0.6)

    # Quantity mismatch
    if abs(mismatch_pct) > MISMATCH_CRITICAL_PCT:
        violations.append(f"Critical quantity mismatch: {mismatch_pct:.1f}% (>{MISMATCH_CRITICAL_PCT}%)")
        rule_score = max(rule_score, 0.9)
    elif abs(mismatch_pct) > MISMATCH_HIGH_PCT:
        violations.append(f"High quantity mismatch: {mismatch_pct:.1f}% (>{MISMATCH_HIGH_PCT}%)")
        rule_score = max(rule_score, 0.55)

    # Stock dropped more than delivered (possible diversion)
    if sb > 0 and sa < sb * 0.5 and mismatch < 0:
        violations.append("Stock dropped >50% unexpectedly — possible diversion")
        rule_score = max(rule_score, 0.8)

    return {"violations": violations, "reasons": violations or [], "rule_score": rule_score}


# ── Severity ──────────────────────────────────────────────────────────────────

def _severity(score: float, rule: dict) -> str:
    violations = rule.get("violations", [])
    critical_keywords = ("negative stock", "critical", "diversion")
    if any(any(k in v.lower() for k in critical_keywords) for v in violations):
        return "CRITICAL"
    if score >= 0.75:
        return "HIGH"
    if score >= 0.45:
        return "MEDIUM"
    return "LOW"


# ── Module-level singleton ────────────────────────────────────────────────────

engine = AnomalyEngine()
