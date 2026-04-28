"""
Anomaly detection for SMART-ALLOT.

Detects unusual demand patterns using:
1. Z-Score method   — flags values > threshold standard deviations from group mean
2. IQR method       — flags values outside [Q1 - k*IQR, Q3 + k*IQR]
3. Isolation Forest — unsupervised ML for multivariate anomalies
4. Consecutive spike detection — flags N-consecutive above-normal months

Each record is assigned an anomaly_score and a flag.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

log = logging.getLogger(__name__)

ANOMALY_FEATURE_COLS = [
    "demand_kg",
    "beneficiary_count",
    "utilization_rate",
    "demand_growth_rate",
]


# ── Config ─────────────────────────────────────────────────────────────────────

@dataclass
class AnomalyConfig:
    zscore_threshold:    float = 3.0     # Flag if |z| > this
    iqr_multiplier:      float = 2.5     # Flag if outside Q1 - k*IQR
    isolation_contamination: float = 0.04  # Expected fraction of anomalies
    consecutive_months:  int   = 2       # Alert if N months above 2σ in a row
    spike_multiplier:    float = 2.0     # Demand > 2× rolling_6m_mean → spike


DEFAULT_CONFIG = AnomalyConfig()


# ── Result ─────────────────────────────────────────────────────────────────────

@dataclass
class AnomalyRecord:
    fps_id:         str
    district:       str
    mandal:         str
    commodity:      str
    date:           str
    demand_kg:      float
    expected_range: str
    anomaly_score:  float
    severity:       str       # "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
    reasons:        list[str]
    is_anomaly:     bool


# ── Helpers ────────────────────────────────────────────────────────────────────

def _severity(score: float) -> str:
    if score >= 0.85:
        return "CRITICAL"
    if score >= 0.65:
        return "HIGH"
    if score >= 0.40:
        return "MEDIUM"
    return "LOW"


def _group_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Add per-group mean/std for demand."""
    stats = (
        df.groupby(["fps_id", "commodity"])["demand_kg"]
          .agg(["mean", "std"])
          .rename(columns={"mean": "_grp_mean", "std": "_grp_std"})
          .reset_index()
    )
    return df.merge(stats, on=["fps_id", "commodity"], how="left")


# ── Method 1: Z-Score ──────────────────────────────────────────────────────────

def detect_zscore(df: pd.DataFrame, cfg: AnomalyConfig = DEFAULT_CONFIG) -> pd.Series:
    """Returns Series of z-scores (per fps_id × commodity group)."""
    df = _group_stats(df)
    std = df["_grp_std"].replace(0, np.nan).fillna(1)
    return ((df["demand_kg"] - df["_grp_mean"]) / std).abs()


# ── Method 2: IQR ─────────────────────────────────────────────────────────────

def detect_iqr(df: pd.DataFrame, cfg: AnomalyConfig = DEFAULT_CONFIG) -> pd.Series:
    """Returns boolean Series — True if record is an IQR outlier."""
    flags = pd.Series(False, index=df.index)
    for (fps, comm), grp in df.groupby(["fps_id", "commodity"]):
        q1, q3 = grp["demand_kg"].quantile([0.25, 0.75])
        iqr    = q3 - q1
        lo, hi = q1 - cfg.iqr_multiplier * iqr, q3 + cfg.iqr_multiplier * iqr
        flags.loc[grp.index] = (grp["demand_kg"] < lo) | (grp["demand_kg"] > hi)
    return flags


# ── Method 3: Isolation Forest ────────────────────────────────────────────────

def fit_isolation_forest(
    df: pd.DataFrame,
    cfg: AnomalyConfig = DEFAULT_CONFIG,
) -> tuple[IsolationForest, StandardScaler]:
    cols = [c for c in ANOMALY_FEATURE_COLS if c in df.columns]
    X = df[cols].fillna(0).values
    scaler = StandardScaler()
    Xs     = scaler.fit_transform(X)
    clf    = IsolationForest(
        contamination=cfg.isolation_contamination,
        random_state=42,
        n_estimators=200,
    )
    clf.fit(Xs)
    return clf, scaler


def predict_isolation_forest(
    clf: IsolationForest,
    scaler: StandardScaler,
    df: pd.DataFrame,
) -> pd.Series:
    """Returns anomaly score in [0, 1] where 1 = most anomalous."""
    cols = [c for c in ANOMALY_FEATURE_COLS if c in df.columns]
    X  = df[cols].fillna(0).values
    Xs = scaler.transform(X)
    # decision_function: lower = more anomalous; normalize to [0,1]
    scores = clf.decision_function(Xs)
    # Invert so higher score = more anomalous
    norm = (scores.max() - scores) / (scores.max() - scores.min() + 1e-9)
    return pd.Series(norm.clip(0, 1), index=df.index)


# ── Method 4: Spike detection ──────────────────────────────────────────────────

def detect_spikes(df: pd.DataFrame, cfg: AnomalyConfig = DEFAULT_CONFIG) -> pd.Series:
    """Returns boolean Series — True if demand > spike_multiplier × 6-month rolling mean."""
    flags = pd.Series(False, index=df.index)
    df = df.sort_values(["fps_id", "commodity", "date"])
    for (fps, comm), grp in df.groupby(["fps_id", "commodity"]):
        roll_mean = grp["demand_kg"].shift(1).rolling(6, min_periods=2).mean()
        spike = grp["demand_kg"] > cfg.spike_multiplier * roll_mean
        flags.loc[grp.index] = spike.fillna(False)
    return flags


# ── Combined detector ──────────────────────────────────────────────────────────

class AnomalyDetector:
    def __init__(self, cfg: AnomalyConfig = DEFAULT_CONFIG) -> None:
        self.cfg     = cfg
        self._clf:    Optional[IsolationForest] = None
        self._scaler: Optional[StandardScaler]  = None
        self._trained = False

    def fit(self, df: pd.DataFrame) -> "AnomalyDetector":
        self._clf, self._scaler = fit_isolation_forest(df, self.cfg)
        self._trained = True
        return self

    def detect(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Run all detectors and combine into a scored DataFrame.
        Adds columns: anomaly_score, is_anomaly, severity, anomaly_reasons.
        """
        df = df.copy()

        # Ensure needed columns
        if "demand_growth_rate" not in df.columns:
            df["demand_growth_rate"] = (
                df.groupby(["fps_id", "commodity"])["demand_kg"]
                  .pct_change(fill_method=None)
                  .fillna(0)
                  .clip(-1, 5)
            )
        if "utilization_rate" not in df.columns:
            denom = df["stock_allocated_kg"].replace(0, np.nan) if "stock_allocated_kg" in df.columns else pd.Series(np.nan, index=df.index)
            df["utilization_rate"] = (df.get("stock_utilized_kg", pd.Series(np.nan, index=df.index)) / denom).clip(0, 1.2).fillna(0)

        z_scores   = detect_zscore(df, self.cfg)
        iqr_flags  = detect_iqr(df, self.cfg)
        spike_flags = detect_spikes(df, self.cfg)

        if self._trained and self._clf is not None:
            iso_scores = predict_isolation_forest(self._clf, self._scaler, df)
        else:
            iso_scores = pd.Series(0.0, index=df.index)

        # Composite score
        z_norm   = (z_scores / self.cfg.zscore_threshold).clip(0, 1)
        iso_norm = iso_scores
        iqr_norm = iqr_flags.astype(float)
        spk_norm = spike_flags.astype(float)

        anomaly_score = (
            0.35 * z_norm +
            0.30 * iso_norm +
            0.20 * iqr_norm +
            0.15 * spk_norm
        ).clip(0, 1)

        df["anomaly_score"] = anomaly_score.round(3)
        df["is_anomaly"]    = (
            (z_scores > self.cfg.zscore_threshold) |
            iqr_flags |
            spike_flags |
            (iso_scores > 0.7)
        )

        # Build reasons list
        reasons_list = []
        for i in df.index:
            reasons = []
            if z_scores[i] > self.cfg.zscore_threshold:
                reasons.append(f"Z-score={z_scores[i]:.1f} (>{self.cfg.zscore_threshold})")
            if iqr_flags[i]:
                reasons.append("IQR outlier")
            if spike_flags[i]:
                reasons.append(f"Demand spike (>{self.cfg.spike_multiplier}× rolling avg)")
            if iso_scores[i] > 0.7:
                reasons.append(f"Isolation Forest score={iso_scores[i]:.2f}")
            reasons_list.append(reasons if reasons else ["No anomaly"])
        df["anomaly_reasons"] = reasons_list
        df["severity"]        = df["anomaly_score"].apply(_severity)

        return df

    def get_anomaly_records(self, df: pd.DataFrame) -> list[AnomalyRecord]:
        """Return only flagged records as AnomalyRecord objects."""
        detected = self.detect(df)
        flagged  = detected[detected["is_anomaly"]].copy()

        records = []
        for _, row in flagged.iterrows():
            grp_mean = detected[
                (detected["fps_id"] == row["fps_id"]) &
                (detected["commodity"] == row["commodity"])
            ]["demand_kg"].mean()
            grp_std = detected[
                (detected["fps_id"] == row["fps_id"]) &
                (detected["commodity"] == row["commodity"])
            ]["demand_kg"].std()
            lo = max(0, grp_mean - 2 * grp_std)
            hi = grp_mean + 2 * grp_std
            records.append(AnomalyRecord(
                fps_id=str(row.get("fps_id", "")),
                district=str(row.get("district", "")),
                mandal=str(row.get("mandal", "")),
                commodity=str(row.get("commodity", "")),
                date=str(row["date"])[:10],
                demand_kg=float(row["demand_kg"]),
                expected_range=f"{lo:.0f}–{hi:.0f} kg",
                anomaly_score=float(row["anomaly_score"]),
                severity=str(row["severity"]),
                reasons=list(row["anomaly_reasons"]),
                is_anomaly=True,
            ))
        return records

    def save(self, path: str | Path) -> None:
        joblib.dump({"clf": self._clf, "scaler": self._scaler, "trained": self._trained}, path)

    @classmethod
    def load(cls, path: str | Path, cfg: AnomalyConfig = DEFAULT_CONFIG) -> "AnomalyDetector":
        d = joblib.load(path)
        obj = cls(cfg)
        obj._clf     = d["clf"]
        obj._scaler  = d["scaler"]
        obj._trained = d["trained"]
        return obj
