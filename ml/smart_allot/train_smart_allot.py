from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.compose import ColumnTransformer
from sklearn.inspection import permutation_importance
from sklearn.impute import SimpleImputer
from sklearn.metrics import confusion_matrix, mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from xgboost import XGBRegressor


NON_NUMERIC_COLUMNS = ["_id", "id", "month", "state_name", "state_code", "district_name", "district_code"]
AP_STATE_NAME = "Andhra Pradesh"
COMMODITY_MAP = [
    {
        "item_name": "Rice",
        "allocated_col": "total_rice_qty_allocated",
        "distributed_cols": [
            "total_rice_distributed_unautomated",
            "total_rice_distributed_automated",
        ],
    },
    {
        "item_name": "Wheat",
        "allocated_col": "total_wheat_qty_allocated",
        "distributed_cols": [
            "total_wheat_distributed_unautomated",
            "total_wheat_distributed_automated",
        ],
    },
    {
        "item_name": "Coarse Grain",
        "allocated_col": "total_coarse_grain_qty_allocated",
        "distributed_cols": [
            "total_coarse_grain_distributed_unautomated",
            "total_coarse_grain_distributed_automated",
        ],
    },
    {
        "item_name": "Fortified Rice",
        "allocated_col": "total_fortified_rice_qty_allocated",
        "distributed_cols": [
            "total_fortified_rice_distributed_unautomated",
            "total_fortified_rice_distributed_automated",
        ],
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train SMARTAllot commodity-wise forecasting model")
    parser.add_argument("--data", required=True, help="Path to the raw CSV dataset")
    parser.add_argument(
        "--artifacts-dir",
        default=str(Path(__file__).resolve().parent / "artifacts"),
        help="Directory to store cleaned data, model artifacts, and recommendations",
    )
    return parser.parse_args()


def safe_mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    denominator = np.where(np.abs(y_true) < 1e-6, 1.0, np.abs(y_true))
    return float(np.mean(np.abs((y_true - y_pred) / denominator)) * 100)


def weighted_absolute_percentage_error(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    denominator = np.sum(np.abs(y_true))
    if denominator < 1e-6:
        return 0.0
    return float(np.sum(np.abs(y_true - y_pred)) / denominator * 100)


def load_and_clean_data(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["month"] = pd.to_datetime(df["month"], errors="coerce")
    df["state_name"] = df["state_name"].astype(str).str.strip()
    df["district_name"] = df["district_name"].astype(str).str.strip()
    df["district_name"] = df["district_name"].replace({"nan": np.nan, "None": np.nan, "": np.nan})

    district_map = (
        df.loc[df["district_name"].notna(), ["state_name", "district_code", "district_name"]]
        .drop_duplicates()
        .groupby(["state_name", "district_code"])["district_name"]
        .agg(lambda names: names.mode().iloc[0] if not names.mode().empty else names.iloc[0])
    )

    missing_mask = df["district_name"].isna()
    if missing_mask.any():
        df.loc[missing_mask, "district_name"] = df.loc[missing_mask].apply(
            lambda row: district_map.get(
                (row["state_name"], row["district_code"]),
                f"District_{int(row['district_code'])}",
            ),
            axis=1,
        )

    numeric_cols = [col for col in df.columns if col not in NON_NUMERIC_COLUMNS]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    aggregate_map = {col: "sum" for col in numeric_cols}
    aggregate_map["state_code"] = "first"
    aggregate_map["district_code"] = "first"

    cleaned = (
        df.dropna(subset=["month", "state_name", "district_name"])
        .groupby(["month", "state_name", "district_name"], as_index=False, dropna=False)
        .agg(aggregate_map)
        .sort_values(["state_name", "district_name", "month"])
        .reset_index(drop=True)
    )
    return cleaned


def build_item_panel(cleaned: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for cfg in COMMODITY_MAP:
        item_df = cleaned[
            [
                "month",
                "state_name",
                "state_code",
                "district_name",
                "district_code",
                cfg["allocated_col"],
                *cfg["distributed_cols"],
                "total_qty_allocated",
            ]
        ].copy()
        item_df["item_name"] = cfg["item_name"]
        item_df["allocated_qty"] = item_df[cfg["allocated_col"]]
        item_df["distributed_qty"] = item_df[cfg["distributed_cols"]].sum(axis=1)
        item_df = item_df.drop(columns=[cfg["allocated_col"], *cfg["distributed_cols"]])
        frames.append(item_df)

    panel = pd.concat(frames, ignore_index=True)
    panel = panel[(panel["allocated_qty"] > 0) | (panel["distributed_qty"] > 0)].copy()
    panel["distribution_to_allocation_ratio"] = np.where(
        panel["allocated_qty"] > 0,
        panel["distributed_qty"] / panel["allocated_qty"],
        0.0,
    )
    panel["allocation_gap"] = panel["allocated_qty"] - panel["distributed_qty"]
    panel = panel.sort_values(["state_name", "district_name", "item_name", "month"]).reset_index(drop=True)
    return panel


def add_time_series_features(panel: pd.DataFrame) -> pd.DataFrame:
    data = panel.copy()
    data["series_id"] = data["state_name"] + " | " + data["district_name"] + " | " + data["item_name"]
    data["month_num"] = data["month"].dt.month
    data["year"] = data["month"].dt.year
    data["month_sin"] = np.sin(2 * np.pi * data["month_num"] / 12.0)
    data["month_cos"] = np.cos(2 * np.pi * data["month_num"] / 12.0)
    data["trend_index"] = data.groupby("series_id").cumcount()

    lag_targets = [
        "distributed_qty",
        "allocated_qty",
        "distribution_to_allocation_ratio",
        "allocation_gap",
        "total_qty_allocated",
    ]
    for feature in lag_targets:
        for lag in [1, 2, 3, 6, 12]:
            data[f"{feature}_lag_{lag}"] = data.groupby("series_id")[feature].shift(lag)

    grouped_distributed = data.groupby("series_id")["distributed_qty"]
    grouped_allocated = data.groupby("series_id")["allocated_qty"]
    for window in [3, 6, 12]:
        data[f"distributed_roll_mean_{window}"] = grouped_distributed.shift(1).rolling(window).mean()
        data[f"distributed_roll_std_{window}"] = grouped_distributed.shift(1).rolling(window).std()
        data[f"allocated_roll_mean_{window}"] = grouped_allocated.shift(1).rolling(window).mean()

    data["target_next_month"] = data.groupby("series_id")["distributed_qty"].shift(-1)
    data["forecast_month"] = data.groupby("series_id")["month"].shift(-1)
    return data


def build_training_frame(featured: pd.DataFrame) -> pd.DataFrame:
    required_lags = [
        "distributed_qty_lag_1",
        "distributed_qty_lag_2",
        "distributed_qty_lag_3",
        "allocated_qty_lag_1",
        "distributed_roll_mean_3",
    ]
    return featured.dropna(subset=required_lags + ["target_next_month", "forecast_month"]).copy()


def feature_columns() -> tuple[list[str], list[str], list[str]]:
    categorical_features = ["state_name", "district_name", "item_name"]
    numeric_features = [
        "state_code",
        "district_code",
        "month_num",
        "year",
        "month_sin",
        "month_cos",
        "trend_index",
        "distributed_qty_lag_1",
        "distributed_qty_lag_2",
        "distributed_qty_lag_3",
        "distributed_qty_lag_6",
        "distributed_qty_lag_12",
        "allocated_qty_lag_1",
        "allocated_qty_lag_2",
        "allocated_qty_lag_3",
        "allocated_qty_lag_6",
        "allocated_qty_lag_12",
        "distribution_to_allocation_ratio_lag_1",
        "distribution_to_allocation_ratio_lag_2",
        "allocation_gap_lag_1",
        "allocation_gap_lag_2",
        "total_qty_allocated_lag_1",
        "distributed_roll_mean_3",
        "distributed_roll_mean_6",
        "distributed_roll_mean_12",
        "distributed_roll_std_3",
        "distributed_roll_std_6",
        "distributed_roll_std_12",
        "allocated_roll_mean_3",
        "allocated_roll_mean_6",
        "allocated_roll_mean_12",
    ]
    return categorical_features + numeric_features, categorical_features, numeric_features


def build_preprocessor(categorical_features: list[str], numeric_features: list[str]) -> ColumnTransformer:
    return ColumnTransformer(
        transformers=[
            ("num", SimpleImputer(strategy="median"), numeric_features),
            (
                "cat",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                categorical_features,
            ),
        ]
    )


def plot_learning_curves(evals_result: dict, output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(evals_result["validation_0"]["rmse"], label="Train RMSE", linewidth=2)
    ax.plot(evals_result["validation_1"]["rmse"], label="Validation RMSE", linewidth=2)
    ax.set_title("SMARTAllot Training Curve")
    ax.set_xlabel("Boosting Round")
    ax.set_ylabel("RMSE")
    ax.legend()
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def plot_actual_vs_predicted(scored_test: pd.DataFrame, output_path: Path) -> None:
    sample = scored_test.sample(min(3000, len(scored_test)), random_state=42)
    fig, ax = plt.subplots(figsize=(7, 7))
    sns.scatterplot(data=sample, x="target_next_month", y="prediction", hue="item_name", alpha=0.65, ax=ax, s=35)
    low = min(sample["target_next_month"].min(), sample["prediction"].min())
    high = max(sample["target_next_month"].max(), sample["prediction"].max())
    ax.plot([low, high], [low, high], linestyle="--", color="black", linewidth=1.5)
    ax.set_title("Actual vs Predicted Demand")
    ax.set_xlabel("Actual")
    ax.set_ylabel("Predicted")
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def plot_residuals(scored_test: pd.DataFrame, output_path: Path) -> None:
    residuals = scored_test["target_next_month"] - scored_test["prediction"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    sns.histplot(residuals, bins=50, kde=True, ax=axes[0], color="#185c73")
    axes[0].set_title("Residual Distribution")
    axes[0].set_xlabel("Actual - Predicted")
    sns.scatterplot(x=scored_test["prediction"], y=residuals, hue=scored_test["item_name"], alpha=0.5, ax=axes[1], s=22)
    axes[1].axhline(0, linestyle="--", color="black", linewidth=1.2)
    axes[1].set_title("Residuals vs Predicted")
    axes[1].set_xlabel("Predicted")
    axes[1].set_ylabel("Residual")
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def plot_feature_importance(importances: pd.DataFrame, output_path: Path) -> None:
    top = importances.head(20).copy()
    fig, ax = plt.subplots(figsize=(10, 7))
    sns.barplot(data=top, x="importance", y="feature", ax=ax, color="#b56a17")
    ax.set_title("Top Feature Importances")
    ax.set_xlabel("Importance")
    ax.set_ylabel("")
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def plot_demand_band_confusion(scored_test: pd.DataFrame, output_path: Path) -> dict:
    labels = ["Very Low", "Low", "Medium", "High", "Very High"]
    y_true_bins = pd.qcut(
        scored_test["target_next_month"].rank(method="first"),
        q=min(5, scored_test["target_next_month"].nunique()),
        labels=labels[: min(5, scored_test["target_next_month"].nunique())],
    )
    quantiles = scored_test["target_next_month"].quantile(np.linspace(0, 1, len(y_true_bins.cat.categories) + 1)).to_numpy()
    y_pred_bins = pd.cut(
        scored_test["prediction"],
        bins=np.unique(quantiles),
        labels=y_true_bins.cat.categories if len(np.unique(quantiles)) - 1 == len(y_true_bins.cat.categories) else None,
        include_lowest=True,
    )
    valid = y_pred_bins.notna() & y_true_bins.notna()
    cm = confusion_matrix(y_true_bins[valid], y_pred_bins[valid], labels=list(y_true_bins.cat.categories))
    fig, ax = plt.subplots(figsize=(7, 6))
    sns.heatmap(cm, annot=True, fmt="d", cmap="YlGnBu", xticklabels=y_true_bins.cat.categories, yticklabels=y_true_bins.cat.categories, ax=ax)
    ax.set_title("Demand Band Confusion Matrix")
    ax.set_xlabel("Predicted Demand Band")
    ax.set_ylabel("Actual Demand Band")
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
    return {
        "labels": list(map(str, y_true_bins.cat.categories)),
        "matrix": cm.tolist(),
    }


def train_model(train_df: pd.DataFrame, artifacts_dir: Path) -> tuple[dict[str, object], dict[str, float], pd.DataFrame]:
    all_features, categorical_features, numeric_features = feature_columns()

    split_cutoff = train_df["forecast_month"].max() - pd.DateOffset(months=6)
    fit_df = train_df[train_df["forecast_month"] < split_cutoff].copy()
    test_df = train_df[train_df["forecast_month"] >= split_cutoff].copy()
    val_cutoff = fit_df["forecast_month"].max() - pd.DateOffset(months=3)
    train_inner = fit_df[fit_df["forecast_month"] < val_cutoff].copy()
    val_df = fit_df[fit_df["forecast_month"] >= val_cutoff].copy()

    preprocessor = build_preprocessor(categorical_features, numeric_features)
    X_train_inner = preprocessor.fit_transform(train_inner[all_features])
    X_val = preprocessor.transform(val_df[all_features])
    X_fit = preprocessor.transform(fit_df[all_features])
    X_test = preprocessor.transform(test_df[all_features])

    model = XGBRegressor(
        n_estimators=900,
        learning_rate=0.03,
        max_depth=6,
        min_child_weight=3,
        subsample=0.85,
        colsample_bytree=0.85,
        objective="reg:squarederror",
        random_state=42,
        n_jobs=4,
        eval_metric="rmse",
        early_stopping_rounds=60,
    )

    model.fit(
        X_train_inner,
        train_inner["target_next_month"],
        eval_set=[(X_train_inner, train_inner["target_next_month"]), (X_val, val_df["target_next_month"])],
        verbose=False,
    )

    predictions = model.predict(X_test)

    metrics = {
        "train_rows": int(len(fit_df)),
        "test_rows": int(len(test_df)),
        "mae": float(mean_absolute_error(test_df["target_next_month"], predictions)),
        "rmse": float(np.sqrt(mean_squared_error(test_df["target_next_month"], predictions))),
        "mape_percent": safe_mape(test_df["target_next_month"].to_numpy(), predictions),
        "wape_percent": weighted_absolute_percentage_error(test_df["target_next_month"].to_numpy(), predictions),
    }

    scored_test = test_df[
        ["forecast_month", "state_name", "district_name", "district_code", "item_name", "target_next_month"]
    ].copy()
    scored_test["prediction"] = predictions
    scored_test["absolute_error"] = np.abs(scored_test["target_next_month"] - scored_test["prediction"])
    scored_test["residual"] = scored_test["target_next_month"] - scored_test["prediction"]

    evals_result = model.evals_result()
    plot_learning_curves(evals_result, artifacts_dir / "training_curve.png")
    plot_actual_vs_predicted(scored_test, artifacts_dir / "actual_vs_predicted.png")
    plot_residuals(scored_test, artifacts_dir / "residual_diagnostics.png")

    feature_names = preprocessor.get_feature_names_out()
    feature_importances = pd.DataFrame(
        {
            "feature": feature_names,
            "importance": model.feature_importances_,
        }
    ).sort_values("importance", ascending=False)
    feature_importances.to_csv(artifacts_dir / "feature_importance.csv", index=False)
    plot_feature_importance(feature_importances, artifacts_dir / "feature_importance.png")

    demand_band_confusion = plot_demand_band_confusion(scored_test, artifacts_dir / "demand_band_confusion_matrix.png")

    best_iteration = getattr(model, "best_iteration", None)
    best_ntree_limit = best_iteration + 1 if best_iteration is not None else 700

    final_preprocessor = build_preprocessor(categorical_features, numeric_features)
    X_full = final_preprocessor.fit_transform(train_df[all_features])
    final_model = XGBRegressor(
        n_estimators=max(best_ntree_limit, 50),
        learning_rate=0.03,
        max_depth=6,
        min_child_weight=3,
        subsample=0.85,
        colsample_bytree=0.85,
        objective="reg:squarederror",
        random_state=42,
        n_jobs=4,
        eval_metric="rmse",
    )
    final_model.fit(X_full, train_df["target_next_month"], verbose=False)

    model_bundle = {
        "preprocessor": final_preprocessor,
        "model": final_model,
        "feature_columns": all_features,
        "feature_names": list(feature_names),
    }

    metrics["best_iteration"] = int(best_iteration) if best_iteration is not None else None
    metrics["validation_rows"] = int(len(val_df))
    metrics["demand_band_confusion"] = demand_band_confusion

    return model_bundle, metrics, scored_test


def build_latest_predictions(featured: pd.DataFrame, model_bundle: dict[str, object]) -> pd.DataFrame:
    all_features, _, _ = feature_columns()
    preprocessor = model_bundle["preprocessor"]
    model = model_bundle["model"]

    latest = (
        featured.sort_values(["state_name", "district_name", "item_name", "month"])
        .groupby(["state_name", "district_name", "item_name"], as_index=False)
        .tail(1)
        .copy()
    )
    latest = latest.dropna(subset=["distributed_qty_lag_1", "distributed_roll_mean_3"]).copy()
    latest["forecast_next_month"] = model.predict(preprocessor.transform(latest[all_features]))
    latest["volatility_proxy"] = latest["distributed_roll_std_6"].fillna(latest["distributed_roll_std_3"]).fillna(0.0)
    latest["carryover_stock_proxy"] = latest["allocation_gap_lag_1"].clip(lower=0.0)
    latest["safety_stock"] = np.maximum(latest["forecast_next_month"] * 0.10, latest["volatility_proxy"] * 0.50)
    latest["recommended_allotment"] = (
        latest["forecast_next_month"] + latest["safety_stock"] - latest["carryover_stock_proxy"]
    ).clip(lower=0.0)
    latest["forecast_for_month"] = latest["month"] + pd.offsets.MonthBegin(1)
    latest["model_strategy"] = "XGBoost global panel forecast with district, commodity, lag, rolling, and seasonal features"

    columns = [
        "forecast_for_month",
        "state_name",
        "district_name",
        "district_code",
        "item_name",
        "forecast_next_month",
        "safety_stock",
        "carryover_stock_proxy",
        "recommended_allotment",
        "volatility_proxy",
        "distributed_qty_lag_1",
        "allocated_qty_lag_1",
        "model_strategy",
    ]
    return latest[columns].sort_values(["state_name", "district_name", "item_name"]).reset_index(drop=True)


def main() -> None:
    args = parse_args()
    data_path = Path(args.data)
    artifacts_dir = Path(args.artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    cleaned = load_and_clean_data(data_path)
    item_panel = build_item_panel(cleaned)
    featured = add_time_series_features(item_panel)
    train_df = build_training_frame(featured)
    model_bundle, metrics, scored_test = train_model(train_df, artifacts_dir)
    recommendations = build_latest_predictions(featured, model_bundle)

    ap_recommendations = recommendations[
        (recommendations["state_name"] == AP_STATE_NAME)
        & (~recommendations["district_name"].astype(str).str.startswith("District_", na=False))
    ].copy()

    cleaned.to_csv(artifacts_dir / "cleaned_panel.csv", index=False)
    item_panel.to_csv(artifacts_dir / "item_panel.csv", index=False)
    train_df.to_csv(artifacts_dir / "train_dataset.csv", index=False)
    scored_test.to_csv(artifacts_dir / "test_predictions.csv", index=False)
    ap_recommendations.to_csv(artifacts_dir / "andhra_pradesh_recommendations.csv", index=False)
    joblib.dump(model_bundle, artifacts_dir / "smart_allot_model.joblib")

    metrics_payload = {
        "dataset": {
            "raw_file": str(data_path),
            "cleaned_rows": int(len(cleaned)),
            "item_panel_rows": int(len(item_panel)),
            "training_rows": int(len(train_df)),
            "states": int(cleaned["state_name"].nunique()),
            "districts": int(cleaned["district_name"].nunique()),
            "date_min": str(item_panel["month"].min().date()),
            "date_max": str(item_panel["month"].max().date()),
            "items": sorted(item_panel["item_name"].unique().tolist()),
        },
        "metrics": metrics,
        "andhra_pradesh": {
            "districts_forecasted": int(ap_recommendations["district_name"].nunique()),
            "item_rows_forecasted": int(len(ap_recommendations)),
            "forecast_month": str(ap_recommendations["forecast_for_month"].max().date()) if not ap_recommendations.empty else None,
            "total_recommended_allotment": float(ap_recommendations["recommended_allotment"].sum()) if not ap_recommendations.empty else 0.0,
        },
        "artifacts_dir": str(artifacts_dir),
    }

    with (artifacts_dir / "model_metrics.json").open("w", encoding="utf-8") as f:
        json.dump(metrics_payload, f, indent=2)

    print(json.dumps(metrics_payload, indent=2))


if __name__ == "__main__":
    main()
