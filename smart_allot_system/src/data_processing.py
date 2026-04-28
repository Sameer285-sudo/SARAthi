"""
Data processing pipeline for SMART-ALLOT.

Handles:
- Loading and schema validation
- Missing-value imputation
- Outlier clipping
- Feature engineering (lag, rolling, seasonality)
- Normalization
- Prophet-ready time-series formatting
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
import joblib

warnings.filterwarnings("ignore")

# ── Constants ──────────────────────────────────────────────────────────────────

REQUIRED_COLS = [
    "date", "district", "mandal", "fps_id", "commodity",
    "beneficiary_count", "demand_kg", "stock_allocated_kg",
]

LOCATION_COLS  = ["district", "mandal", "fps_id", "commodity"]
NUMERIC_COLS   = [
    "beneficiary_count", "demand_kg", "stock_allocated_kg",
    "stock_utilized_kg", "stock_remaining_kg",
]
SEASONAL_IDX = {
    1: 1.08, 2: 1.05, 3: 1.00, 4: 0.96, 5: 0.93, 6: 0.95,
    7: 0.98, 8: 0.99, 9: 1.00, 10: 1.02, 11: 1.06, 12: 1.10,
}


# ── Loading ────────────────────────────────────────────────────────────────────

def load_dataset(path: str | Path) -> pd.DataFrame:
    """Load CSV/Excel and enforce minimal schema."""
    p = Path(path)
    if p.suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(p)
    else:
        df = pd.read_csv(p)

    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Dataset missing required columns: {missing}")

    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


# ── Cleaning ───────────────────────────────────────────────────────────────────

def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """Impute missing values and clip outliers."""
    df = df.copy()

    # Add derived columns if absent
    if "stock_utilized_kg" not in df.columns:
        df["stock_utilized_kg"] = np.nan
    if "stock_remaining_kg" not in df.columns:
        df["stock_remaining_kg"] = np.nan

    # Fill numeric nulls using median per (fps_id, commodity)
    for col in NUMERIC_COLS:
        if col in df.columns:
            group_median = df.groupby(["fps_id", "commodity"])[col].transform("median")
            df[col] = df[col].fillna(group_median).fillna(df[col].median())

    # Enforce non-negative values
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = df[col].clip(lower=0)

    # Clip outliers at 1st / 99th percentile per commodity
    for col in ["demand_kg", "stock_allocated_kg", "stock_utilized_kg"]:
        if col in df.columns:
            lo = df.groupby("commodity")[col].transform(lambda x: x.quantile(0.01))
            hi = df.groupby("commodity")[col].transform(lambda x: x.quantile(0.99))
            df[col] = df[col].clip(lo, hi)

    # Derived utilization rate
    denom = df["stock_allocated_kg"].replace(0, np.nan)
    df["utilization_rate"] = (df["stock_utilized_kg"] / denom).clip(0, 1.2)

    return df


# ── Feature Engineering ────────────────────────────────────────────────────────

def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds:
    - month, quarter, year, seasonal_index
    - per-FPS-commodity lag features: lag_1m, lag_3m, lag_6m, lag_12m
    - rolling averages: roll_3m, roll_6m, roll_12m
    - demand_variability (rolling std)
    - demand_growth_rate (month-on-month % change)
    - beneficiary_demand_ratio
    """
    df = df.copy()
    df["month"]          = df["date"].dt.month
    df["quarter"]        = df["date"].dt.quarter
    df["year"]           = df["date"].dt.year
    df["seasonal_index"] = df["month"].map(SEASONAL_IDX)

    # Month sine/cosine encoding for cyclical seasonality
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)

    df["beneficiary_demand_ratio"] = df["demand_kg"] / df["beneficiary_count"].replace(0, np.nan)

    # Sort for correct lag computation
    df = df.sort_values(["fps_id", "commodity", "date"]).reset_index(drop=True)

    grp = df.groupby(["fps_id", "commodity"])["demand_kg"]

    for lag in [1, 3, 6, 12]:
        df[f"demand_lag_{lag}m"] = grp.shift(lag)

    for window in [3, 6, 12]:
        df[f"demand_roll_{window}m_mean"] = grp.shift(1).rolling(window, min_periods=1).mean().values
        df[f"demand_roll_{window}m_std"]  = grp.shift(1).rolling(window, min_periods=1).std().values

    df["demand_growth_rate"] = grp.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)

    # Fill lag NaNs with group mean
    lag_cols = [c for c in df.columns if c.startswith("demand_lag") or c.startswith("demand_roll")]
    for col in lag_cols:
        group_mean = df.groupby(["fps_id", "commodity"])[col].transform("mean")
        df[col] = df[col].fillna(group_mean).fillna(0)

    df["demand_growth_rate"] = df["demand_growth_rate"].fillna(0).clip(-1, 5)

    return df


# ── Normalization ──────────────────────────────────────────────────────────────

FEATURE_COLS = [
    "beneficiary_count", "seasonal_index", "month_sin", "month_cos",
    "beneficiary_demand_ratio",
    "demand_lag_1m", "demand_lag_3m", "demand_lag_6m", "demand_lag_12m",
    "demand_roll_3m_mean", "demand_roll_6m_mean", "demand_roll_12m_mean",
    "demand_roll_3m_std", "demand_roll_6m_std", "demand_roll_12m_std",
    "demand_growth_rate",
]


def get_feature_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in FEATURE_COLS if c in df.columns]


def normalize_features(
    df: pd.DataFrame,
    scaler: Optional[StandardScaler] = None,
    fit: bool = True,
) -> tuple[pd.DataFrame, StandardScaler]:
    """
    Normalize numeric feature columns.
    Returns (transformed_df, fitted_scaler).
    Pass scaler + fit=False to transform test data.
    """
    df = df.copy()
    cols = get_feature_cols(df)

    if scaler is None:
        scaler = StandardScaler()

    if fit:
        df[cols] = scaler.fit_transform(df[cols].astype(float))
    else:
        df[cols] = scaler.transform(df[cols].astype(float))

    return df, scaler


def save_scaler(scaler: StandardScaler, path: str | Path) -> None:
    joblib.dump(scaler, path)


def load_scaler(path: str | Path) -> StandardScaler:
    return joblib.load(path)


# ── Train / test split ─────────────────────────────────────────────────────────

def train_test_split_temporal(
    df: pd.DataFrame,
    test_months: int = 3,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Chronological split: last `test_months` months → test set.
    """
    cutoff = df["date"].max() - pd.DateOffset(months=test_months - 1)
    cutoff = cutoff.replace(day=1)
    train  = df[df["date"] < cutoff].copy()
    test   = df[df["date"] >= cutoff].copy()
    return train, test


# ── Prophet formatter ──────────────────────────────────────────────────────────

def to_prophet_format(
    df: pd.DataFrame,
    group_key: tuple[str, ...],
    target_col: str = "demand_kg",
) -> pd.DataFrame:
    """
    Return a DataFrame with columns [ds, y] for a specific group.
    group_key: e.g. ("Guntur", "Rajupalem", "FPS-GUN-RAJ-01", "Rice")
    """
    loc_cols = LOCATION_COLS[: len(group_key)]
    mask = pd.Series([True] * len(df), index=df.index)
    for col, val in zip(loc_cols, group_key):
        mask &= df[col] == val

    subset = df[mask][["date", target_col]].dropna()
    subset = subset.rename(columns={"date": "ds", target_col: "y"})
    subset = subset.groupby("ds", as_index=False)["y"].sum()
    return subset.sort_values("ds").reset_index(drop=True)


# ── Aggregation helpers ────────────────────────────────────────────────────────

def aggregate(
    df: pd.DataFrame,
    level: str = "district",  # "district" | "mandal" | "fps"
) -> pd.DataFrame:
    """Aggregate to district / mandal / fps level for dashboard charts."""
    group_map = {
        "district": ["date", "district", "commodity"],
        "mandal":   ["date", "district", "mandal", "commodity"],
        "fps":      ["date", "district", "mandal", "fps_id", "commodity"],
    }
    grp_cols = group_map.get(level, ["date", "district", "commodity"])
    num_cols = [c for c in NUMERIC_COLS if c in df.columns] + ["utilization_rate"]
    agg_dict = {c: "sum" if c != "utilization_rate" else "mean" for c in num_cols if c in df.columns}
    if "beneficiary_count" in agg_dict:
        agg_dict["beneficiary_count"] = "sum"
    return df.groupby(grp_cols).agg(agg_dict).reset_index()


# ── Full pipeline ──────────────────────────────────────────────────────────────

def run_pipeline(
    path: str | Path,
    test_months: int = 3,
    scaler_save_path: Optional[str | Path] = None,
) -> dict:
    """
    End-to-end preprocessing pipeline.
    Returns dict with keys: train, test, scaler, full_df
    """
    raw  = load_dataset(path)
    cleaned = clean_data(raw)
    featured = engineer_features(cleaned)

    train, test = train_test_split_temporal(featured, test_months)

    train_norm, scaler = normalize_features(train, fit=True)
    test_norm, _       = normalize_features(test,  scaler=scaler, fit=False)

    if scaler_save_path:
        save_scaler(scaler, scaler_save_path)

    return {
        "full_df":  featured,
        "train":    train_norm,
        "test":     test_norm,
        "scaler":   scaler,
        "raw":      raw,
    }
