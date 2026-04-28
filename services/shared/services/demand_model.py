from __future__ import annotations

"""
Demand forecasting model trained from dataset/clean_transactions.csv (DB-style dataset).

Why this exists:
- The UI/bot wants real ML artifacts (curves, matrices) rather than hardcoded insights.
- TransactionRecord commodities are verbose (e.g., "FRice (Kgs)"), while users say "rice".
- The SMARTAllot /predict-demand endpoint should prefer a trained model when available,
  and fall back to a deterministic DB baseline otherwise.

We train TWO models:
1) Regression forecaster (GradientBoostingRegressor) predicting next-month quantity_kgs.
2) Derived classification model predicting movement class (DOWN / FLAT / UP) so we can
   produce confusion matrix, ROC/PR curves, precision/recall/F1.
"""

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    PrecisionRecallDisplay,
    RocCurveDisplay,
    classification_report,
    confusion_matrix,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)
from sklearn.model_selection import TimeSeriesSplit, learning_curve
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


def _try_import_pandas():
    """
    Lazy pandas import to keep services online on low-memory Windows machines.
    Training endpoints should fail gracefully with a clear message.
    """

    try:
        import pandas as pd  # type: ignore

        return pd
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Pandas is unavailable on this machine (often due to low virtual memory / paging file). "
            f"Import error: {type(exc).__name__}: {exc}"
        )


MONTH_ORDER = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
_MONTH_TO_NUM = {m: i + 1 for i, m in enumerate(MONTH_ORDER)}


def _root_dir() -> Path:
    # services/shared/services/demand_model.py -> parents[3] = repo root
    return Path(__file__).resolve().parents[3]


ART_DIR = _root_dir() / "ml" / "smart_allot" / "artifacts"
PLOTS_DIR = ART_DIR / "plots"
REG_MODEL_PATH = ART_DIR / "db_demand_regressor.joblib"
CLS_MODEL_PATH = ART_DIR / "db_demand_movement_classifier.joblib"
METRICS_PATH = ART_DIR / "db_demand_model_metrics.json"


def _ensure_dirs() -> None:
    ART_DIR.mkdir(parents=True, exist_ok=True)
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)


def _commodity_alias_to_dataset_label(token: str | None) -> str | None:
    """
    Map user-friendly commodity names to the actual TransactionRecord commodity strings.
    Keep this conservative: we prefer deterministic mapping over fuzzy matching.
    """
    if not token:
        return None
    t = token.strip().lower()
    return {
        "rice": "FRice (Kgs)",
        "fortified rice": "FRice (Kgs)",
        "wheat": "Whole Wheat Atta (Kgs)",
        "atta": "Whole Wheat Atta (Kgs)",
        "sugar": "SUGAR HALF KG (Kgs)",
        "dal": "Flood Dal (Kgs)",
        "pulses": "Flood Dal (Kgs)",
        "oil": "Flood Poil (Kgs)",
    }.get(t)


def normalize_commodity(value: str | None) -> str | None:
    """
    Normalize commodity input:
    - If already matches dataset label, keep it.
    - If it's a known alias (rice/wheat/sugar/oil/dal), map to dataset label.
    """
    if not value:
        return None
    v = value.strip()
    mapped = _commodity_alias_to_dataset_label(v)
    return mapped or v


def _load_clean_transactions_long(csv_path: Path):
    """
    Parse dataset/clean_transactions.csv (wide) -> long format:
      year, month, district, afso, fps_id, commodity, quantity_kgs, cards
    """
    pd = _try_import_pandas()
    df = pd.read_csv(csv_path)

    # Defensive rename for common schema variants
    df = df.rename(columns={
        "dtstrict": "district",
        "fps": "fps_id",
    })

    required = {"year", "district", "afso", "fps_id"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"clean_transactions.csv missing columns: {missing}")

    # Known columns (kept in sync with shared/seed.py)
    commodities = [
        "FRice (Kgs)",
        "Flood Dal (Kgs)",
        "Flood Onion (Kgs)",
        "Flood Poil (Kgs)",
        "Flood Potato (Kgs)",
        "Flood Rice (Kgs)",
        "Flood Sugar HK (Kgs)",
        "Jowar (Kgs)",
        "RG Dal One kg Pkt (Kgs)",
        "Raagi (Kgs)",
        "SUGAR HALF KG (Kgs)",
        "WM Atta Pkt (Kgs)",
        "Whole Wheat Atta (Kgs)",
    ]
    months = ["January", "February", "March", "April"]

    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        fps_id = str(int(r["fps_id"])).strip() if pd.notna(r["fps_id"]) else str(r["fps_id"]).strip()
        district = str(r["district"]).strip()
        afso = str(r["afso"]).strip()
        year = int(r["year"])

        for m in months:
            cards = int(r.get(f"{m}_Cards", 0) or 0)
            for c in commodities:
                col = f"{m}_{c}"
                if col not in df.columns:
                    continue
                qty = float(r.get(col, 0) or 0.0)
                # Clean: negative -> 0
                if not math.isfinite(qty) or qty < 0:
                    qty = 0.0
                rows.append({
                    "year": year,
                    "month": m,
                    "month_num": _MONTH_TO_NUM.get(m, 1),
                    "district": district,
                    "afso": afso,
                    "fps_id": fps_id,
                    "commodity": c,
                    "quantity_kgs": qty,
                    "cards": int(cards or 0),
                })

    out = pd.DataFrame(rows)
    if out.empty:
        raise ValueError("Parsed 0 rows from clean_transactions.csv")

    out["date"] = pd.to_datetime(out["year"].astype(str) + "-" + out["month_num"].astype(str).str.zfill(2) + "-01")
    return out


def _add_lags(df):
    df = df.sort_values(["district", "afso", "fps_id", "commodity", "date"]).reset_index(drop=True)
    key = ["district", "afso", "fps_id", "commodity"]
    g = df.groupby(key, sort=False)
    df["lag_1"] = g["quantity_kgs"].shift(1)
    df["lag_2"] = g["quantity_kgs"].shift(2)
    df["lag_3"] = g["quantity_kgs"].shift(3)
    # Use groupby.transform — avoids slow apply(tuple, axis=1) on large DataFrames
    df["roll_mean_3"] = g["quantity_kgs"].transform(
        lambda x: x.shift(1).rolling(3, min_periods=1).mean()
    )
    df["roll_std_3"] = g["quantity_kgs"].transform(
        lambda x: x.shift(1).rolling(3, min_periods=1).std()
    )
    df["qty_per_card"]  = df["quantity_kgs"] / np.maximum(df["cards"].astype(float), 1.0)
    df["lag1_per_card"] = df["lag_1"] / np.maximum(df["cards"].astype(float), 1.0)
    for c in ["lag_2", "lag_3", "roll_mean_3", "roll_std_3", "lag1_per_card"]:
        if c in df.columns:
            df[c] = df[c].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return df


def _movement_class(y, lag1):
    """
    DOWN / FLAT / UP based on pct change vs lag_1.
    This is only for reporting (confusion matrix / ROC/PR), not the primary forecast.
    """
    base = lag1.replace(0, np.nan)
    pct = (y - lag1) / base
    # threshold tuned for small month-to-month noise
    out = np.where(pct <= -0.05, "DOWN", np.where(pct >= 0.05, "UP", "FLAT"))
    pd = _try_import_pandas()
    return pd.Series(out, index=y.index)


@dataclass
class TrainedDemandModel:
    reg: Pipeline
    cls: Pipeline
    feature_names: list[str]
    trained_at: str
    csv_sha256: str
    metrics: dict[str, Any]


def _sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def train_from_clean_transactions(csv_path: Path) -> TrainedDemandModel:
    """
    Train regression + classification models from the canonical dataset CSV.
    Saves models + plots + metrics to ml/smart_allot/artifacts/.
    """
    _ensure_dirs()

    t0 = datetime.utcnow()
    df = _load_clean_transactions_long(csv_path)
    df = _add_lags(df)

    # Remove rows without lag_1 (first observation per series) for supervised training.
    df_trainable = df.dropna(subset=["lag_1"]).copy()

    # Temporal split: last available month per series is test.
    # This avoids leaking future information.
    df_trainable["is_test"] = False
    last_idx = (
        df_trainable
        .sort_values(["district", "afso", "fps_id", "commodity", "date"])
        .groupby(["district", "afso", "fps_id", "commodity"])
        .tail(1)
        .index
    )
    df_trainable.loc[last_idx, "is_test"] = True

    train_df = df_trainable[df_trainable["is_test"] == False].copy()  # noqa: E712
    test_df = df_trainable[df_trainable["is_test"] == True].copy()    # noqa: E712

    y_train = train_df["quantity_kgs"].astype(float)
    y_test = test_df["quantity_kgs"].astype(float)

    # Features
    cat_cols = ["district", "afso", "commodity"]
    num_cols = ["month_num", "cards", "lag_1", "lag_2", "lag_3", "roll_mean_3", "roll_std_3", "qty_per_card", "lag1_per_card"]

    pre = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), cat_cols),
            ("num", "passthrough", num_cols),
        ],
        remainder="drop",
        sparse_threshold=0.3,
    )

    reg = Pipeline(steps=[
        ("pre", pre),
        ("model", GradientBoostingRegressor(
            random_state=42,
            n_estimators=220,
            learning_rate=0.05,
            max_depth=3,
            subsample=0.9,
        )),
    ])

    reg.fit(train_df[cat_cols + num_cols], y_train)

    yhat_train = reg.predict(train_df[cat_cols + num_cols])
    yhat_test = reg.predict(test_df[cat_cols + num_cols])

    reg_metrics = {
        "train_mae": float(mean_absolute_error(y_train, yhat_train)),
        "test_mae": float(mean_absolute_error(y_test, yhat_test)),
        "train_rmse": float(np.sqrt(mean_squared_error(y_train, yhat_train))),
        "test_rmse": float(np.sqrt(mean_squared_error(y_test, yhat_test))),
        "test_r2": float(r2_score(y_test, yhat_test)),
    }

    # Derived classification target
    cls_target_train = _movement_class(train_df["quantity_kgs"], train_df["lag_1"])
    cls_target_test = _movement_class(test_df["quantity_kgs"], test_df["lag_1"])

    cls = Pipeline(steps=[
        ("pre", pre),
        ("clf", LogisticRegression(
            max_iter=2000,
            class_weight="balanced",
            n_jobs=1,
        )),
    ])
    cls.fit(train_df[cat_cols + num_cols], cls_target_train)

    cls_pred = cls.predict(test_df[cat_cols + num_cols])
    cls_report = classification_report(cls_target_test, cls_pred, output_dict=True, zero_division=0)

    # Plotting (matplotlib is in requirements)
    import matplotlib.pyplot as plt

    # 1) "Training curve" proxy: staged MAE across boosting stages on train/test
    model: GradientBoostingRegressor = reg.named_steps["model"]
    Xtr = reg.named_steps["pre"].transform(train_df[cat_cols + num_cols])
    Xte = reg.named_steps["pre"].transform(test_df[cat_cols + num_cols])
    tr_mae, te_mae = [], []
    for p_tr, p_te in zip(model.staged_predict(Xtr), model.staged_predict(Xte)):
        tr_mae.append(mean_absolute_error(y_train, p_tr))
        te_mae.append(mean_absolute_error(y_test, p_te))
    plt.figure(figsize=(9.5, 4.2))
    plt.plot(tr_mae, label="Train MAE")
    plt.plot(te_mae, label="Validation/Test MAE")
    plt.title("Training Curve (staged MAE)")
    plt.xlabel("Boosting Stage")
    plt.ylabel("MAE")
    plt.grid(True, alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "training_curve_mae.png", dpi=140)
    plt.close()

    # 2) Residual plot (test)
    resid = y_test.values - yhat_test
    plt.figure(figsize=(9.5, 4.2))
    plt.scatter(yhat_test, resid, s=14, alpha=0.35)
    plt.axhline(0, color="#0B3A73", linewidth=1)
    plt.title("Residuals (Test)")
    plt.xlabel("Predicted (kg)")
    plt.ylabel("Residual (true - pred)")
    plt.grid(True, alpha=0.2)
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "residuals_scatter.png", dpi=140)
    plt.close()

    # 3) Feature importance (top 20)
    try:
        feat_names = list(reg.named_steps["pre"].get_feature_names_out())
        importances = model.feature_importances_
        top = np.argsort(importances)[::-1][:20]
        plt.figure(figsize=(9.5, 5.4))
        plt.barh([feat_names[i] for i in top][::-1], [importances[i] for i in top][::-1])
        plt.title("Feature Importance (Top 20)")
        plt.tight_layout()
        plt.savefig(PLOTS_DIR / "feature_importance_top20.png", dpi=140)
        plt.close()
        feature_names = feat_names
    except Exception:
        feature_names = []

    # 4) Learning curve (time series split)
    try:
        tscv = TimeSeriesSplit(n_splits=3)
        X = df_trainable.sort_values("date")[cat_cols + num_cols]
        y = df_trainable.sort_values("date")["quantity_kgs"].astype(float)
        sizes, tr_scores, te_scores = learning_curve(
            reg,
            X,
            y,
            cv=tscv,
            scoring="neg_mean_absolute_error",
            train_sizes=np.linspace(0.25, 1.0, 5),
            n_jobs=1,
        )
        tr_mean = -tr_scores.mean(axis=1)
        te_mean = -te_scores.mean(axis=1)
        plt.figure(figsize=(9.5, 4.2))
        plt.plot(sizes, tr_mean, marker="o", label="Train MAE")
        plt.plot(sizes, te_mean, marker="o", label="CV MAE")
        plt.title("Learning Curve (MAE)")
        plt.xlabel("Training Samples")
        plt.ylabel("MAE")
        plt.grid(True, alpha=0.25)
        plt.legend()
        plt.tight_layout()
        plt.savefig(PLOTS_DIR / "learning_curve_mae.png", dpi=140)
        plt.close()
    except Exception:
        pass

    # 5) Confusion matrix (movement classification)
    cm = confusion_matrix(cls_target_test, cls_pred, labels=["DOWN", "FLAT", "UP"])
    disp = ConfusionMatrixDisplay(cm, display_labels=["DOWN", "FLAT", "UP"])
    fig, ax = plt.subplots(figsize=(6.6, 5.4))
    disp.plot(ax=ax, cmap="Blues", colorbar=False, values_format="d")
    plt.title("Confusion Matrix (Demand Movement)")
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "confusion_matrix.png", dpi=140)
    plt.close(fig)

    # 6) ROC / PR curves (one-vs-rest). Use "UP" as positive class for a simple read.
    try:
        proba = cls.predict_proba(test_df[cat_cols + num_cols])
        classes = list(cls.named_steps["clf"].classes_)
        if "UP" in classes:
            up_idx = classes.index("UP")
            y_bin = (cls_target_test.values == "UP").astype(int)
            RocCurveDisplay.from_predictions(y_bin, proba[:, up_idx])
            plt.title("ROC Curve (UP vs Rest)")
            plt.tight_layout()
            plt.savefig(PLOTS_DIR / "roc_curve_up.png", dpi=140)
            plt.close()

            PrecisionRecallDisplay.from_predictions(y_bin, proba[:, up_idx])
            plt.title("Precision-Recall Curve (UP vs Rest)")
            plt.tight_layout()
            plt.savefig(PLOTS_DIR / "pr_curve_up.png", dpi=140)
            plt.close()
    except Exception:
        pass

    metrics = {
        "trained_at_utc": t0.isoformat() + "Z",
        "dataset_csv": str(csv_path),
        "dataset_sha256": _sha256_file(csv_path),
        "rows_long": int(len(df)),
        "rows_trainable": int(len(df_trainable)),
        "regression": reg_metrics,
        "classification_movement": {
            "labels": ["DOWN", "FLAT", "UP"],
            "report": cls_report,
        },
        "plots": sorted([p.name for p in PLOTS_DIR.glob("*.png")]),
    }

    joblib.dump(reg, REG_MODEL_PATH)
    joblib.dump(cls, CLS_MODEL_PATH)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    return TrainedDemandModel(
        reg=reg,
        cls=cls,
        feature_names=feature_names,
        trained_at=metrics["trained_at_utc"],
        csv_sha256=metrics["dataset_sha256"],
        metrics=metrics,
    )


def is_trained() -> bool:
    return REG_MODEL_PATH.exists() and CLS_MODEL_PATH.exists() and METRICS_PATH.exists()


_reg_cache: Pipeline | None = None
_reg_mtime: float = 0.0


def load_regressor() -> Pipeline | None:
    global _reg_cache, _reg_mtime
    if not REG_MODEL_PATH.exists():
        return None
    mtime = REG_MODEL_PATH.stat().st_mtime
    if _reg_cache is None or mtime != _reg_mtime:
        _reg_cache = joblib.load(REG_MODEL_PATH)
        _reg_mtime = mtime
    return _reg_cache


def load_metrics() -> dict[str, Any] | None:
    if not METRICS_PATH.exists():
        return None
    try:
        return json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _next_year_month(year: int, month_num: int, step: int) -> tuple[int, int]:
    total = year * 12 + (month_num - 1) + step
    return total // 12, (total % 12) + 1


def _date_str(year: int, month_num: int) -> str:
    return f"{year:04d}-{month_num:02d}-01"


def predict_future_from_db(
    *,
    db_rows: list[dict[str, Any]],
    future_periods: int,
) -> list[dict[str, Any]]:
    """
    Predict future demand using the trained regressor, given DB-style history rows.

    db_rows must contain:
      year, month, district, afso, fps_id, commodity, quantity_kgs, cards
    """
    reg = load_regressor()
    if reg is None:
        raise FileNotFoundError("Demand regressor not trained.")

    pd = _try_import_pandas()
    df = pd.DataFrame(db_rows)
    if df.empty:
        return []

    key_cols = ["district", "afso", "fps_id", "commodity"]
    cat_cols = ["district", "afso", "commodity"]
    num_cols = ["month_num", "cards", "lag_1", "lag_2", "lag_3",
                "roll_mean_3", "roll_std_3", "qty_per_card", "lag1_per_card"]

    df["month_num"] = df["month"].map(_MONTH_TO_NUM).fillna(1).astype(int)

    # Skip full _add_lags pass — only last 3 observations per series are needed to seed
    # lag_1/lag_2/lag_3 for the next-month prediction.
    df = df.sort_values(key_cols + ["year", "month_num"]).reset_index(drop=True)
    tails = df.groupby(key_cols, sort=False).tail(3).copy()

    # rank: 0 = most recent (time T), 1 = T-1, 2 = T-2
    tails["_rank"] = tails.groupby(key_cols, sort=False).cumcount(ascending=False)

    seed_df  = tails[tails["_rank"] == 0].set_index(key_cols).copy()   # time T
    qty_t1   = tails[tails["_rank"] == 1].set_index(key_cols)["quantity_kgs"]  # T-1
    qty_t2   = tails[tails["_rank"] == 2].set_index(key_cols)["quantity_kgs"]  # T-2

    # lag_1 for predicting T+1 = qty at T;   lag_2 = qty at T-1;   lag_3 = qty at T-2
    # (mirrors what _add_lags produces for the most-recent seed row)
    seed_df["lag_1"] = seed_df["quantity_kgs"]                        # T
    seed_df["lag_2"] = qty_t1.reindex(seed_df.index).fillna(0.0)     # T-1
    seed_df["lag_3"] = qty_t2.reindex(seed_df.index).fillna(0.0)     # T-2
    seed_df = seed_df.reset_index()

    out: list[dict[str, Any]] = []

    last_rows = seed_df.copy()

    # If lag_1 missing, we cannot forecast for that series (not enough history)
    last_rows = last_rows.dropna(subset=["lag_1"])
    if last_rows.empty:
        return []

    metrics = load_metrics() or {}
    test_mae = float(metrics.get("regression", {}).get("test_mae", 0.0) or 0.0)

    n = len(last_rows)

    # Vectorised state — one entry per series; updated each step
    lag1_v = last_rows["lag_1"].fillna(0).values.astype(float)   # qty at T
    lag2_v = last_rows["lag_2"].fillna(0).values.astype(float)   # qty at T-1
    lag3_v = last_rows["lag_3"].fillna(0).values.astype(float)   # qty at T-2
    cards_v = last_rows["cards"].fillna(0).values.astype(float)
    year_v  = last_rows["year"].values.astype(int)
    month_v = last_rows["month_num"].values.astype(int)

    district_v  = last_rows["district"].values.astype(str)
    afso_v      = last_rows["afso"].values.astype(str)
    fps_v       = last_rows["fps_id"].values.astype(str)
    commodity_v = last_rows["commodity"].values.astype(str)

    out: list[dict[str, Any]] = []

    for step in range(1, future_periods + 1):
        # Compute (year, month) for every series in one vectorised step
        total_m = year_v * 12 + (month_v - 1) + step
        fy_v = total_m // 12
        fm_v = (total_m % 12) + 1

        roll_mean = (lag1_v + lag2_v + lag3_v) / 3.0
        roll_std  = np.std(np.vstack([lag1_v, lag2_v, lag3_v]), axis=0)
        qty_per_card  = lag1_v / np.maximum(cards_v, 1.0)

        # Build all feature rows for this step as one DataFrame → single predict call
        X_batch = pd.DataFrame({
            "district":      district_v,
            "afso":          afso_v,
            "commodity":     commodity_v,
            "month_num":     fm_v.astype(int),
            "cards":         cards_v.astype(int),
            "lag_1":         lag1_v,
            "lag_2":         lag2_v,
            "lag_3":         lag3_v,
            "roll_mean_3":   roll_mean,
            "roll_std_3":    roll_std,
            "qty_per_card":  qty_per_card,
            "lag1_per_card": qty_per_card,
        })[cat_cols + num_cols]

        preds = np.maximum(reg.predict(X_batch), 0.0)

        conf = 0.82 if step == 1 else max(0.62, 0.82 - (step - 1) * 0.06)
        band_v = np.maximum(test_mae, preds * 0.08) * (1.0 + (step - 1) * 0.08)

        for i in range(n):
            out.append({
                "location":        fps_v[i],
                "district":        district_v[i],
                "afso":            afso_v[i],
                "commodity":       commodity_v[i],
                "date":            _date_str(int(fy_v[i]), int(fm_v[i])),
                "predicted_demand": round(float(preds[i]), 2),
                "lower_bound":      round(max(float(preds[i]) - float(band_v[i]), 0.0), 2),
                "upper_bound":      round(float(preds[i]) + float(band_v[i]), 2),
                "confidence_score": round(conf, 2),
                "model_used":       "DB_GBR_V1",
            })

        # Advance rolling lags for next step
        lag3_v, lag2_v, lag1_v = lag2_v, lag1_v, preds

    return out
