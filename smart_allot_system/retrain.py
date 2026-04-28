"""
Retraining pipeline for SMART-ALLOT.

Usage:
  python retrain.py --data data/sample_dataset.csv --test-months 3

Outputs:
  models/baseline.pkl
  models/prophet/
  models/anomaly_detector.pkl
  models/scaler.pkl
  models/eval_report.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("retrain")

MODELS_DIR = Path("models")


def retrain(data_path: str, test_months: int = 3) -> dict:
    t0 = time.perf_counter()

    # ── Imports ────────────────────────────────────────────────────────────────
    from src.data_processing import run_pipeline
    from src.modeling import SmartAllotForecaster
    from src.anomaly_detection import AnomalyDetector
    from src.evaluation import generate_eval_report

    MODELS_DIR.mkdir(exist_ok=True)

    # ── Step 1: Preprocessing ─────────────────────────────────────────────────
    log.info("Step 1/4 — Running preprocessing pipeline ...")
    pipeline = run_pipeline(
        path=data_path,
        test_months=test_months,
        scaler_save_path=MODELS_DIR / "scaler.pkl",
    )
    train     = pipeline["train"]
    test      = pipeline["test"]
    full_df   = pipeline["full_df"]

    log.info(
        "Data loaded: %d train rows, %d test rows, %d total",
        len(train), len(test), len(full_df),
    )

    # ── Step 2: Train forecasting models ──────────────────────────────────────
    log.info("Step 2/4 — Training forecasting models ...")
    forecaster = SmartAllotForecaster(models_dir=MODELS_DIR)
    metrics    = forecaster.fit(train, test)
    forecaster.save()
    log.info("Forecaster metrics: %s", metrics)

    # ── Step 3: Train anomaly detector ────────────────────────────────────────
    log.info("Step 3/4 — Training anomaly detector ...")
    detector = AnomalyDetector()
    detector.fit(full_df)
    detector.save(MODELS_DIR / "anomaly_detector.pkl")
    anomaly_count = len(detector.get_anomaly_records(full_df))
    log.info("Anomaly detector fitted. Found %d anomalies in training set.", anomaly_count)

    # ── Step 4: Evaluation report ─────────────────────────────────────────────
    log.info("Step 4/4 — Generating evaluation report ...")
    report = generate_eval_report(train, test, forecaster.baseline)
    report["anomalies_in_training_set"] = anomaly_count
    report["training_duration_seconds"] = round(time.perf_counter() - t0, 1)

    report_path = MODELS_DIR / "eval_report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str))
    log.info("Evaluation report saved to %s", report_path)

    # ── Summary ────────────────────────────────────────────────────────────────
    log.info("=" * 60)
    log.info("Retraining complete in %.1fs", time.perf_counter() - t0)
    log.info("MAE : %.2f kg | RMSE : %.2f kg | WAPE : %.1f%%",
             metrics["mae"], metrics["rmse"], metrics["wape_pct"])
    log.info("Models saved to %s/", MODELS_DIR)
    log.info("=" * 60)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="SMART-ALLOT retraining pipeline")
    parser.add_argument("--data",        default="data/sample_dataset.csv", help="Path to dataset CSV")
    parser.add_argument("--test-months", default=3, type=int,               help="Number of months for test set")
    args = parser.parse_args()

    if not Path(args.data).exists():
        log.error("Dataset not found: %s — run generate_sample_data.py first.", args.data)
        sys.exit(1)

    retrain(data_path=args.data, test_months=args.test_months)


if __name__ == "__main__":
    main()
