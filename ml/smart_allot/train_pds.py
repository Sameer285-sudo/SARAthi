"""
PDS Training Pipeline — GradientBoosting on clean_transactions.csv (2026 Jan-Apr)

Train:  January + February + March  (3 months)
Test:   April                        (holdout)
Predict: May 2026                    (next-month forecast)

Usage (from project root):
    python ml/smart_allot/train_pds.py

Artifacts written to ml/smart_allot/artifacts/:
    smart_allot_model.joblib           (model + encodings)
    model_metrics.json                 (overwritten)
    andhra_pradesh_recommendations.csv (overwritten — May 2026 forecasts)
    test_predictions.csv               (April actual vs predicted)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT          = Path(__file__).resolve().parent.parent.parent
DATA_PATH     = ROOT / "dataset" / "clean_transactions.csv"
ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS_DIR.mkdir(exist_ok=True)

# ── Constants ──────────────────────────────────────────────────────────────────
MONTHS = {"January": 1, "February": 2, "March": 3, "April": 4}

COMMODITIES = {
    "FRice (Kgs)":             "Fine Rice",
    "Jowar (Kgs)":             "Jowar",
    "RG Dal One kg Pkt (Kgs)": "Dal",
    "Raagi (Kgs)":             "Raagi",
    "SUGAR HALF KG (Kgs)":     "Sugar",
    "WM Atta Pkt (Kgs)":       "Atta",
}

SEASONAL_IDX = {1: 1.08, 2: 1.05, 3: 1.00, 4: 0.96, 5: 0.93}

FEATURE_COLS = [
    "cards", "per_card",
    "lag_1m", "lag_2m", "lag_3m", "roll_mean_3m",
    "seasonal_idx", "month_sin", "month_cos",
    "district_code", "commodity_code", "month",
]

TARGET = "kgs"


# ── 1. Load and reshape (wide → long) ─────────────────────────────────────────

def load_and_reshape(path: Path) -> pd.DataFrame:
    """Read wide-format CSV; produce one row per FPS × month × commodity."""
    raw = pd.read_csv(path)
    # Drop duplicate columns that pandas renamed with .1, .2 suffix
    raw = raw.loc[:, ~raw.columns.str.match(r".*\.\d+$")]

    chunks = []
    for month_name, month_num in MONTHS.items():
        cards_col = f"{month_name}_Cards"
        if cards_col not in raw.columns:
            continue
        for col_suffix, commodity in COMMODITIES.items():
            col = f"{month_name}_{col_suffix}"
            if col not in raw.columns:
                continue
            sub = raw[["fps", "dtstrict", "afso", "year", cards_col, col]].copy()
            sub.columns = ["fps_id", "district", "afso", "year", "cards", "kgs"]
            sub["month"]     = month_num
            sub["commodity"] = commodity
            sub["fps_id"]    = sub["fps_id"].astype(str)
            sub["kgs"]       = pd.to_numeric(sub["kgs"],   errors="coerce").fillna(0).clip(lower=0)
            sub["cards"]     = pd.to_numeric(sub["cards"], errors="coerce").fillna(0)
            chunks.append(sub)

    if not chunks:
        raise ValueError(
            "No commodity columns found — check MONTHS/COMMODITIES constants match CSV headers"
        )
    return pd.concat(chunks, ignore_index=True)


# ── 2. Feature engineering ─────────────────────────────────────────────────────

def engineer_features(
    df: pd.DataFrame,
    district_map: dict[str, int],
    commodity_map: dict[str, int],
) -> pd.DataFrame:
    df = df.copy().sort_values(["fps_id", "commodity", "month"]).reset_index(drop=True)

    # Per-card demand (kg / beneficiary)
    df["per_card"] = (df["kgs"] / df["cards"].replace(0, np.nan)).fillna(0).clip(0, 2000)

    # Lag features per FPS × commodity
    grp = df.groupby(["fps_id", "commodity"])
    df["lag_1m"] = grp["kgs"].shift(1)
    df["lag_2m"] = grp["kgs"].shift(2)
    df["lag_3m"] = grp["kgs"].shift(3)

    # Rolling 3-month mean (shift-1 to prevent leakage)
    df["roll_mean_3m"] = grp["kgs"].transform(
        lambda s: s.shift(1).rolling(3, min_periods=1).mean()
    )

    # Seasonality
    df["seasonal_idx"] = df["month"].map(SEASONAL_IDX).fillna(1.0)
    df["month_sin"]    = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"]    = np.cos(2 * np.pi * df["month"] / 12)

    # Label encodings (consistent across train/test/predict)
    df["district_code"]  = df["district"].map(district_map).fillna(-1).astype(int)
    df["commodity_code"] = df["commodity"].map(commodity_map).fillna(-1).astype(int)

    # Fill NaN lags with group mean then 0
    for col in ["lag_1m", "lag_2m", "lag_3m", "roll_mean_3m"]:
        gm = grp[col].transform("mean")
        df[col] = df[col].fillna(gm).fillna(0)

    return df


# ── 3. Build May 2026 feature rows ────────────────────────────────────────────

def build_may_features(feat: pd.DataFrame) -> pd.DataFrame:
    """Construct feature rows for month=5 (May) using April as the reference."""
    apr = feat[feat["month"] == 4].copy().reset_index(drop=True)
    mar = feat[feat["month"] == 3][["fps_id", "commodity", "kgs"]].rename(columns={"kgs": "lag_2m"})
    feb = feat[feat["month"] == 2][["fps_id", "commodity", "kgs"]].rename(columns={"kgs": "lag_3m"})

    # roll_mean_3m for May = mean of Feb + Mar + Apr actual kgs
    roll = (
        feat[feat["month"].isin([2, 3, 4])]
        .groupby(["fps_id", "commodity"])["kgs"]
        .mean()
        .reset_index()
        .rename(columns={"kgs": "roll_mean_3m"})
    )

    may = apr[[
        "fps_id", "district", "afso", "year", "commodity",
        "cards", "per_card", "district_code", "commodity_code",
    ]].copy()
    may["month"]  = 5
    may["lag_1m"] = apr["kgs"].values  # April → lag-1 for May

    may = may.merge(mar,  on=["fps_id", "commodity"], how="left")
    may = may.merge(feb,  on=["fps_id", "commodity"], how="left")
    may = may.merge(roll, on=["fps_id", "commodity"], how="left")

    may["seasonal_idx"] = SEASONAL_IDX[5]
    may["month_sin"]    = np.sin(2 * np.pi * 5 / 12)
    may["month_cos"]    = np.cos(2 * np.pi * 5 / 12)

    for col in ["lag_1m", "lag_2m", "lag_3m", "roll_mean_3m", "per_card"]:
        may[col] = may[col].fillna(0)

    return may


# ── 4. Aggregate to district-level recommendations ─────────────────────────────

def build_recommendations(may_df: pd.DataFrame, apr_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate FPS-level May forecasts → district × commodity recommendation rows."""
    dist_may = (
        may_df.groupby(["district", "commodity"])["predicted_kgs"]
        .sum()
        .reset_index()
        .rename(columns={"predicted_kgs": "forecast_next_month"})
    )

    dist_apr = (
        apr_df.groupby(["district", "commodity"])["kgs"]
        .sum()
        .reset_index()
        .rename(columns={"kgs": "distributed_qty_lag_1"})
    )

    recs = dist_may.merge(dist_apr, on=["district", "commodity"], how="left")
    recs["distributed_qty_lag_1"] = recs["distributed_qty_lag_1"].fillna(0)
    recs["allocated_qty_lag_1"]   = recs["distributed_qty_lag_1"]

    recs["safety_stock"]          = (recs["forecast_next_month"] * 0.15).round(2)
    recs["carryover_stock_proxy"] = 0.0
    recs["volatility_proxy"]      = (recs["safety_stock"] * 2).round(2)
    recs["recommended_allotment"] = (
        recs["forecast_next_month"] + recs["safety_stock"]
    ).clip(lower=0).round(2)
    recs["forecast_next_month"]   = recs["forecast_next_month"].round(2)

    # Sequential district codes
    districts = sorted(recs["district"].unique())
    code_map  = {d: i + 1 for i, d in enumerate(districts)}
    recs["district_code"] = recs["district"].map(code_map)

    recs["state_name"]         = "Andhra Pradesh"
    recs["forecast_for_month"] = "2026-05-01"
    recs["item_name"]          = recs["commodity"]
    recs["district_name"]      = recs["district"]
    recs["model_strategy"]     = (
        "GradientBoosting FPS-level forecast — lag, rolling-mean, and seasonal features"
    )

    return recs[[
        "forecast_for_month", "state_name", "district_name", "district_code",
        "item_name", "forecast_next_month", "safety_stock", "carryover_stock_proxy",
        "recommended_allotment", "volatility_proxy",
        "distributed_qty_lag_1", "allocated_qty_lag_1", "model_strategy",
    ]].sort_values(["district_name", "item_name"]).reset_index(drop=True)


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    t0 = time.perf_counter()
    print(f"\n{'='*62}")
    print("  PDS SMART-ALLOT Training Pipeline  (clean_transactions.csv)")
    print(f"{'='*62}")

    # 1. Load
    print("\n[1/5] Loading and reshaping data ...")
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Dataset not found: {DATA_PATH}")
    raw = load_and_reshape(DATA_PATH)
    print(f"  Rows: {len(raw):,} | Districts: {raw['district'].nunique()} | "
          f"FPS: {raw['fps_id'].nunique()} | Commodities: {raw['commodity'].nunique()}")
    print(f"  Months: {sorted(raw['month'].unique())}  "
          f"(1=Jan  2=Feb  3=Mar  4=Apr)")

    # Build deterministic label encodings from entire dataset
    district_map  = {d: i for i, d in enumerate(sorted(raw["district"].unique()))}
    commodity_map = {c: i for i, c in enumerate(sorted(raw["commodity"].unique()))}

    # 2. Feature engineering
    print("[2/5] Engineering features ...")
    feat  = engineer_features(raw, district_map, commodity_map)
    train = feat[feat["month"] <= 3].copy()
    test  = feat[feat["month"] == 4].copy()
    print(f"  Train: {len(train):,} rows (Jan–Mar)  |  Test: {len(test):,} rows (Apr)")

    # 3. Train
    print("[3/5] Training GradientBoostingRegressor (300 trees) ...")
    model = GradientBoostingRegressor(
        n_estimators=300,
        max_depth=5,
        learning_rate=0.08,
        subsample=0.8,
        min_samples_leaf=5,
        random_state=42,
    )
    model.fit(train[FEATURE_COLS].fillna(0).values, train[TARGET].values)

    # 4. Evaluate on April
    print("[4/5] Evaluating on April holdout ...")
    y_true = test[TARGET].values
    y_pred = model.predict(test[FEATURE_COLS].fillna(0).values).clip(0)

    mae  = float(mean_absolute_error(y_true, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    denom = np.where(y_true == 0, 1.0, y_true)
    mape  = float(np.mean(np.abs((y_true - y_pred) / denom)) * 100)
    wape  = float(np.sum(np.abs(y_true - y_pred)) / max(np.sum(y_true), 1.0) * 100)

    print(f"  MAE : {mae:>10.1f} kg")
    print(f"  RMSE: {rmse:>10.1f} kg")
    print(f"  MAPE: {mape:>10.1f} %")
    print(f"  WAPE: {wape:>10.1f} %")

    # 5. Predict May 2026
    print("[5/5] Predicting May 2026 ...")
    may_feat = build_may_features(feat)
    may_feat["predicted_kgs"] = model.predict(
        may_feat[FEATURE_COLS].fillna(0).values
    ).clip(0)

    total_may = may_feat["predicted_kgs"].sum()
    print(f"  Total forecasted demand (May): {total_may:,.0f} kg across "
          f"{may_feat['fps_id'].nunique()} FPS")

    # ── Save artifacts ─────────────────────────────────────────────────────────

    # Model + encodings
    model_path = ARTIFACTS_DIR / "smart_allot_model.joblib"
    joblib.dump({
        "model":         model,
        "feature_cols":  FEATURE_COLS,
        "district_map":  district_map,
        "commodity_map": commodity_map,
        "target":        TARGET,
    }, model_path)

    # Model metrics (service reads this)
    recs = build_recommendations(may_feat, feat[feat["month"] == 4])
    metrics_payload = {
        "dataset": {
            "raw_file":      str(DATA_PATH),
            "total_rows":    len(raw),
            "long_rows":     len(feat),
            "training_rows": len(train),
            "test_rows":     len(test),
            "districts":     raw["district"].nunique(),
            "fps_count":     raw["fps_id"].nunique(),
            "date_min":      "2026-01-01",
            "date_max":      "2026-04-01",
            "items":         sorted(raw["commodity"].unique().tolist()),
        },
        "metrics": {
            "train_rows":      len(train),
            "test_rows":       len(test),
            "mae":             round(mae, 4),
            "rmse":            round(rmse, 4),
            "mape_percent":    round(mape, 4),
            "wape_percent":    round(wape, 4),
            "best_iteration":  300,
            "validation_rows": len(test),
            "demand_band_confusion": {},
        },
        "andhra_pradesh": {
            "districts_forecasted":          recs["district_name"].nunique(),
            "item_rows_forecasted":          len(recs),
            "forecast_month":                "2026-05-01",
            "total_recommended_allotment":   round(float(recs["recommended_allotment"].sum()), 2),
        },
        "artifacts_dir": str(ARTIFACTS_DIR),
    }
    (ARTIFACTS_DIR / "model_metrics.json").write_text(
        json.dumps(metrics_payload, indent=2)
    )

    # Recommendations CSV (service reads this)
    recs.to_csv(ARTIFACTS_DIR / "andhra_pradesh_recommendations.csv", index=False)

    # Test-set predictions (for inspection)
    test_out = test[["fps_id", "district", "commodity", "month", "kgs"]].copy()
    test_out["predicted_kgs"] = y_pred.round(1)
    test_out["error_kg"]      = (y_pred - y_true).round(1)
    test_out.to_csv(ARTIFACTS_DIR / "test_predictions.csv", index=False)

    elapsed = time.perf_counter() - t0
    print(f"\n{'='*62}")
    print(f"  Training complete in {elapsed:.1f}s")
    print(f"  Model    : {model_path.name}")
    print(f"  Metrics  : model_metrics.json")
    print(f"  May recs : andhra_pradesh_recommendations.csv  ({len(recs)} rows)")
    print(f"  Test preds: test_predictions.csv")
    print(f"\n  Districts: {recs['district_name'].nunique()}  |  "
          f"Items: {recs['item_name'].nunique()}  |  "
          f"Total allotment: {recs['recommended_allotment'].sum():,.0f} kg")
    print(f"{'='*62}\n")


if __name__ == "__main__":
    main()
