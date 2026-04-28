"""
Model evaluation and cross-validation for SMART-ALLOT.

Functions:
- compute_metrics      — MAE, RMSE, MAPE, WAPE, R²
- time_series_cv       — expanding-window cross-validation
- evaluate_by_group    — per-district / per-commodity breakdown
- generate_eval_report — dict summary suitable for JSON output
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

log = logging.getLogger(__name__)

TARGET = "demand_kg"


# ── Core metrics ───────────────────────────────────────────────────────────────

def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """
    Returns MAE, RMSE, MAPE, WAPE, R².
    Robust to zero actuals (uses epsilon in MAPE denominator).
    """
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)

    mae  = float(mean_absolute_error(y_true, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    r2   = float(r2_score(y_true, y_pred))

    eps  = 1e-8
    mape = float(np.mean(np.abs((y_true - y_pred) / (np.abs(y_true) + eps))) * 100)
    wape = float(np.sum(np.abs(y_true - y_pred)) / (np.sum(np.abs(y_true)) + eps) * 100)

    bias = float(np.mean(y_pred - y_true))  # positive = over-prediction

    return {
        "mae":      round(mae, 2),
        "rmse":     round(rmse, 2),
        "mape_pct": round(mape, 2),
        "wape_pct": round(wape, 2),
        "r2":       round(r2, 4),
        "bias":     round(bias, 2),
        "n":        len(y_true),
    }


# ── Time-series cross-validation ──────────────────────────────────────────────

def time_series_cv(
    df: pd.DataFrame,
    model_cls,
    n_splits: int = 4,
    test_months: int = 3,
) -> list[dict]:
    """
    Expanding-window cross-validation for time-series models.

    Each fold:
      - train: all data before the test window
      - test : `test_months` months

    Returns list of metric dicts (one per fold).
    """
    from src.data_processing import engineer_features, train_test_split_temporal, normalize_features

    df = df.sort_values("date")
    dates = df["date"].drop_duplicates().sort_values().tolist()
    total_months = len(dates)

    results = []
    step = max(1, total_months // (n_splits + 1))

    for i in range(n_splits):
        split_idx = step * (i + 1) + test_months
        if split_idx >= total_months:
            break

        train_dates = dates[:split_idx - test_months]
        test_dates  = dates[split_idx - test_months: split_idx]

        train = df[df["date"].isin(train_dates)].copy()
        test  = df[df["date"].isin(test_dates)].copy()

        if train.empty or test.empty:
            continue

        try:
            model = model_cls()
            model.fit(train)
            preds = model.predict(test)
            actuals = test[TARGET].values
            metrics = compute_metrics(actuals, preds)
            metrics["fold"] = i + 1
            metrics["train_rows"] = len(train)
            metrics["test_rows"]  = len(test)
            results.append(metrics)
        except Exception as exc:
            log.warning("CV fold %d failed: %s", i + 1, exc)

    return results


# ── Per-group evaluation ───────────────────────────────────────────────────────

def evaluate_by_group(
    df: pd.DataFrame,
    predicted_col: str = "predicted_demand",
    group_cols: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Compute metrics for each sub-group (district, commodity, etc.).
    Expects df to have both actual TARGET and predicted_col.
    """
    if group_cols is None:
        group_cols = ["district", "commodity"]

    rows = []
    for keys, grp in df.groupby(group_cols):
        if not isinstance(keys, tuple):
            keys = (keys,)
        m = compute_metrics(grp[TARGET].values, grp[predicted_col].values)
        row = dict(zip(group_cols, keys))
        row.update(m)
        rows.append(row)

    return pd.DataFrame(rows).sort_values("rmse", ascending=False)


# ── Summary report ─────────────────────────────────────────────────────────────

def generate_eval_report(
    train: pd.DataFrame,
    test: pd.DataFrame,
    model,
    cv_folds: Optional[list[dict]] = None,
) -> dict:
    """
    Generate a comprehensive evaluation report dict.
    model must implement .predict(df) → np.ndarray
    """
    preds   = model.predict(test)
    actuals = test[TARGET].values
    overall = compute_metrics(actuals, preds)

    # Add predictions to test for group analysis
    test_w_pred = test.copy()
    test_w_pred["predicted_demand"] = preds

    by_district  = evaluate_by_group(test_w_pred, group_cols=["district"]).to_dict("records")
    by_commodity = evaluate_by_group(test_w_pred, group_cols=["commodity"]).to_dict("records")

    # Baseline comparison (naive: predict last known value)
    last_known = (
        train.groupby(["fps_id", "commodity"])["demand_kg"]
             .last()
             .reset_index()
             .rename(columns={"demand_kg": "_naive"})
    )
    test_naive = test.merge(last_known, on=["fps_id", "commodity"], how="left")
    naive_pred = test_naive["_naive"].fillna(test_naive[TARGET].mean()).values
    naive_metrics = compute_metrics(actuals, naive_pred)

    report = {
        "overall_metrics":   overall,
        "naive_baseline":    naive_metrics,
        "improvement_over_naive": {
            "mae_reduction_pct":  round((naive_metrics["mae"]  - overall["mae"])  / max(naive_metrics["mae"],  1) * 100, 1),
            "rmse_reduction_pct": round((naive_metrics["rmse"] - overall["rmse"]) / max(naive_metrics["rmse"], 1) * 100, 1),
        },
        "by_district":  by_district,
        "by_commodity": by_commodity,
        "train_rows":   len(train),
        "test_rows":    len(test),
    }

    if cv_folds:
        avg_cv = {
            k: round(float(np.mean([f[k] for f in cv_folds if k in f])), 3)
            for k in ["mae", "rmse", "mape_pct", "wape_pct", "r2"]
        }
        report["cv_average"] = avg_cv
        report["cv_folds"]   = cv_folds

    return report
