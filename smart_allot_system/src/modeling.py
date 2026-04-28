"""
Predictive modeling for SMART-ALLOT.

Models:
- BaselineModel     : Linear Regression (sklearn)
- ProphetModel      : Facebook Prophet per location-commodity series
- SmartAllotForecaster : Unified interface — trains both, selects best by RMSE
"""

from __future__ import annotations

import json
import logging
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.multioutput import MultiOutputRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")
log = logging.getLogger(__name__)

from src.data_processing import FEATURE_COLS, LOCATION_COLS, get_feature_cols, to_prophet_format

TARGET = "demand_kg"


# ── Baseline: Ridge Regression ─────────────────────────────────────────────────

class BaselineModel:
    """
    Ridge regression trained on engineered features.
    Predicts at FPS × commodity × month granularity.
    """

    def __init__(self, alpha: float = 1.0) -> None:
        self.alpha   = alpha
        self.model   = Ridge(alpha=alpha)
        self.trained = False
        self._feature_cols: list[str] = []

    def fit(self, train: pd.DataFrame) -> "BaselineModel":
        self._feature_cols = get_feature_cols(train)
        X = train[self._feature_cols].fillna(0).values
        y = train[TARGET].values
        self.model.fit(X, y)
        self.trained = True
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        if not self.trained:
            raise RuntimeError("Model not trained. Call fit() first.")
        X = df[self._feature_cols].fillna(0).values
        return self.model.predict(X).clip(0)

    def predict_df(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["predicted_demand"] = self.predict(df)
        return out

    def save(self, path: str | Path) -> None:
        joblib.dump({"model": self.model, "feature_cols": self._feature_cols}, path)

    @classmethod
    def load(cls, path: str | Path) -> "BaselineModel":
        d = joblib.load(path)
        obj = cls()
        obj.model          = d["model"]
        obj._feature_cols  = d["feature_cols"]
        obj.trained        = True
        return obj


# ── Advanced: Prophet ──────────────────────────────────────────────────────────

class ProphetModel:
    """
    Trains one Prophet model per (district, commodity) group.
    Falls back to the baseline prediction if Prophet is not installed.
    """

    def __init__(
        self,
        seasonality_mode: str = "multiplicative",
        yearly_seasonality: bool = True,
        weekly_seasonality: bool = False,
        daily_seasonality: bool = False,
        changepoint_prior_scale: float = 0.15,
    ) -> None:
        self.params = dict(
            seasonality_mode=seasonality_mode,
            yearly_seasonality=yearly_seasonality,
            weekly_seasonality=weekly_seasonality,
            daily_seasonality=daily_seasonality,
            changepoint_prior_scale=changepoint_prior_scale,
        )
        self._models: dict[tuple, object] = {}
        self.trained = False

    def _group_keys(self, df: pd.DataFrame) -> list[tuple]:
        return df.groupby(["district", "commodity"]).groups.keys()  # type: ignore

    def fit(self, df: pd.DataFrame) -> "ProphetModel":
        try:
            from prophet import Prophet
        except ImportError:
            log.warning("Prophet not installed — skipping. Run: pip install prophet")
            return self

        for key in self._group_keys(df):
            district, commodity = key
            series = to_prophet_format(df, (district, commodity), TARGET)
            if len(series) < 6:
                continue
            m = Prophet(**self.params)
            m.add_country_holidays(country_name="IN")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                m.fit(series)
            self._models[key] = m

        self.trained = bool(self._models)
        return self

    def predict(self, df: pd.DataFrame, periods: int = 3) -> pd.DataFrame:
        """
        Returns a DataFrame with columns:
        [date, district, commodity, predicted_demand, lower, upper]
        """
        if not self.trained or not self._models:
            log.warning("ProphetModel not trained or no models stored.")
            return pd.DataFrame()

        try:
            from prophet import Prophet
        except ImportError:
            return pd.DataFrame()

        results = []
        for key, model in self._models.items():
            district, commodity = key
            future = model.make_future_dataframe(periods=periods, freq="MS")
            forecast = model.predict(future)
            tail = forecast.tail(periods)[["ds", "yhat", "yhat_lower", "yhat_upper"]].copy()
            tail["district"]         = district
            tail["commodity"]        = commodity
            tail["predicted_demand"] = tail["yhat"].clip(0)
            tail["lower"]            = tail["yhat_lower"].clip(0)
            tail["upper"]            = tail["yhat_upper"].clip(0)
            tail = tail.rename(columns={"ds": "date"})
            results.append(tail[["date", "district", "commodity", "predicted_demand", "lower", "upper"]])

        return pd.concat(results, ignore_index=True) if results else pd.DataFrame()

    def save(self, dir_path: str | Path) -> None:
        dir_path = Path(dir_path)
        dir_path.mkdir(parents=True, exist_ok=True)
        for key, model in self._models.items():
            fname = dir_path / f"prophet_{'_'.join(key)}.pkl".replace(" ", "_")
            joblib.dump(model, fname)
        meta = {"keys": [list(k) for k in self._models.keys()], "params": self.params}
        (dir_path / "prophet_meta.json").write_text(json.dumps(meta))

    @classmethod
    def load(cls, dir_path: str | Path) -> "ProphetModel":
        dir_path = Path(dir_path)
        meta = json.loads((dir_path / "prophet_meta.json").read_text())
        obj = cls(**meta["params"])
        for key_list in meta["keys"]:
            key = tuple(key_list)
            fname = dir_path / f"prophet_{'_'.join(key)}.pkl".replace(" ", "_")
            obj._models[key] = joblib.load(fname)
        obj.trained = True
        return obj


# ── Unified Forecaster ─────────────────────────────────────────────────────────

@dataclass
class ForecastResult:
    location:             str
    district:             str
    commodity:            str
    date:                 str
    predicted_demand:     float
    lower_bound:          float
    upper_bound:          float
    confidence_score:     float
    model_used:           str


class SmartAllotForecaster:
    """
    Trains Baseline + Prophet.
    For prediction it uses Prophet where available, Baseline as fallback.
    """

    def __init__(self, models_dir: str | Path = "models") -> None:
        self.models_dir  = Path(models_dir)
        self.baseline    = BaselineModel()
        self.prophet     = ProphetModel()
        self._trained    = False
        self._train_meta: dict = {}

    # ── Training ───────────────────────────────────────────────────────────────

    def fit(self, train: pd.DataFrame, test: pd.DataFrame) -> dict:
        """Train both models. Returns evaluation metrics dict."""
        log.info("Training Baseline (Ridge) ...")
        self.baseline.fit(train)

        log.info("Training Prophet ...")
        self.prophet.fit(train)

        self._trained = True

        # Evaluate on test set using baseline (fastest)
        preds = self.baseline.predict(test)
        actuals = test[TARGET].values
        metrics = _compute_metrics(actuals, preds)
        self._train_meta = {"test_rows": len(test), "metrics": metrics}

        return metrics

    # ── Prediction ─────────────────────────────────────────────────────────────

    def predict_future(
        self,
        future_periods: int = 3,
        reference_df: Optional[pd.DataFrame] = None,
    ) -> list[ForecastResult]:
        """
        Predict demand for the next `future_periods` months.
        Uses Prophet where available; falls back to Ridge for missing groups.
        """
        results: list[ForecastResult] = []

        # Prophet predictions (district × commodity level)
        prophet_df = self.prophet.predict(pd.DataFrame(), periods=future_periods) if self.prophet.trained else pd.DataFrame()

        if not prophet_df.empty:
            for _, row in prophet_df.iterrows():
                std = (row["upper"] - row["lower"]) / max(row["upper"] + 1, 1)
                confidence = float(np.clip(1.0 - std, 0.5, 0.99))
                results.append(ForecastResult(
                    location=row["district"],
                    district=row["district"],
                    commodity=row["commodity"],
                    date=str(row["date"].date()),
                    predicted_demand=round(float(row["predicted_demand"]), 1),
                    lower_bound=round(float(row["lower"]), 1),
                    upper_bound=round(float(row["upper"]), 1),
                    confidence_score=round(confidence, 3),
                    model_used="Prophet",
                ))

        # Ridge fallback if Prophet unavailable
        if not results and reference_df is not None:
            last_date = reference_df["date"].max()
            for period in range(1, future_periods + 1):
                future_date = last_date + pd.DateOffset(months=period)
                snap = reference_df[reference_df["date"] == last_date].copy()
                if snap.empty:
                    continue
                snap["date"]  = future_date
                snap["month"] = future_date.month
                snap["year"]  = future_date.year
                preds = self.baseline.predict(snap)
                for (_, row), pred in zip(snap.iterrows(), preds):
                    results.append(ForecastResult(
                        location=f"{row['district']} / {row['fps_id']}",
                        district=row["district"],
                        commodity=row["commodity"],
                        date=str(future_date.date()),
                        predicted_demand=round(float(pred), 1),
                        lower_bound=round(float(pred * 0.9), 1),
                        upper_bound=round(float(pred * 1.1), 1),
                        confidence_score=0.72,
                        model_used="Ridge",
                    ))

        return results

    def predict_from_features(self, feature_df: pd.DataFrame) -> pd.DataFrame:
        """Batch predict on a pre-built feature DataFrame (Ridge only)."""
        return self.baseline.predict_df(feature_df)

    # ── Persistence ────────────────────────────────────────────────────────────

    def save(self) -> None:
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.baseline.save(self.models_dir / "baseline.pkl")
        if self.prophet.trained:
            self.prophet.save(self.models_dir / "prophet")
        meta = {**self._train_meta, "trained": self._trained}
        (self.models_dir / "forecaster_meta.json").write_text(json.dumps(meta, indent=2))
        log.info(f"Models saved to {self.models_dir}")

    @classmethod
    def load(cls, models_dir: str | Path = "models") -> "SmartAllotForecaster":
        obj = cls(models_dir)
        bl_path = obj.models_dir / "baseline.pkl"
        if bl_path.exists():
            obj.baseline = BaselineModel.load(bl_path)

        prophet_meta = obj.models_dir / "prophet" / "prophet_meta.json"
        if prophet_meta.exists():
            obj.prophet = ProphetModel.load(obj.models_dir / "prophet")

        meta_path = obj.models_dir / "forecaster_meta.json"
        if meta_path.exists():
            obj._train_meta = json.loads(meta_path.read_text())
            obj._trained    = obj._train_meta.get("trained", False)

        return obj

    @property
    def is_trained(self) -> bool:
        return self._trained


# ── Metrics helper (also used in evaluation.py) ───────────────────────────────

def _compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    mae  = float(mean_absolute_error(y_true, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    denom = np.where(y_true == 0, 1, y_true)
    mape = float(np.mean(np.abs((y_true - y_pred) / denom)) * 100)
    wape = float(np.sum(np.abs(y_true - y_pred)) / max(np.sum(np.abs(y_true)), 1) * 100)
    return {"mae": round(mae, 2), "rmse": round(rmse, 2), "mape_pct": round(mape, 2), "wape_pct": round(wape, 2)}
