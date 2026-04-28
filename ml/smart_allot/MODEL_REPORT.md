# SMARTAllot Model Report

## Dataset Used

- Source: [a2a38535-2208-407b-9e5a-afe2e00088f1.csv](C:\Users\S Sameer\Desktop\pds system\dataset\a2a38535-2208-407b-9e5a-afe2e00088f1.csv)
- Raw rows: `63,425`
- Raw columns: `35`
- Date coverage: `2017-01-01` to `2023-09-01`
- States covered: `34`
- Districts covered after cleaning: `707`

## Cleaning Performed

The raw dataset was not directly safe for forecasting. The following corrections were applied:

- Parsed `month` into a real monthly timestamp.
- Standardized `state_name` and `district_name`.
- Restored missing district names using `state_name + district_code`.
- Converted all quantity fields to numeric.
- Aggregated duplicate `state + district + month` rows by summing quantities.
- Built an `effective_qty_distributed` target:
  - use `total_qty_distributed_epos` when available and positive
  - otherwise use `total_qty_distributed_unautomated + total_qty_distributed_automated`
- Created allocation gap and distribution ratio features.
- Filtered synthetic placeholder districts from the final Andhra Pradesh recommendation sheet.

## Why This Model Was Chosen

The best practical choice for this dataset is a `global XGBoost time-series regression model` with engineered lag and seasonality features.

Why not deep learning:

- Each Andhra Pradesh district has only about `72 to 74` monthly observations after cleaning.
- That is too small for district-level deep learning to be reliably better than gradient-boosted trees.
- For structured tabular time-series data with limited history, boosted trees usually outperform or match DL with lower instability and easier explainability.

Why XGBoost is a strong fit:

- Handles non-linear relationships well
- Works strongly on tabular data
- Performs well with lag and rolling-window features
- Robust against mixed geographic and numeric predictors
- Easier to operationalize for hackathon delivery

## Forecasting Setup

The model predicts `next month's effective demand` for each district using:

- historical distributed quantity lags
- historical allocation lags
- rolling means and rolling standard deviations
- month seasonality features
- geographic identifiers
- allocation gap and utilization ratio features

The recommendation engine then calculates:

- forecast demand
- carryover stock proxy
- safety stock based on volatility
- recommended allotment

## Evaluation Results

- Train rows: `38,784`
- Test rows: `4,330`
- MAE: `476.54`
- RMSE: `1220.38`
- WAPE: `8.03%`

## Important Note On MAPE

The raw `MAPE` appears extremely large because some district-month targets are near zero, and MAPE becomes unstable in such cases. For this dataset, `WAPE` is the more meaningful business metric.

## Andhra Pradesh Output

- Districts forecasted: `13`
- Forecast month in current run: `2023-10-01`
- Total recommended allotment: `145132.68`

## Output Files

- Cleaned panel: [cleaned_panel.csv](C:\Users\S Sameer\Desktop\pds system\ml\smart_allot\artifacts\cleaned_panel.csv)
- Training dataset: [train_dataset.csv](C:\Users\S Sameer\Desktop\pds system\ml\smart_allot\artifacts\train_dataset.csv)
- Test predictions: [test_predictions.csv](C:\Users\S Sameer\Desktop\pds system\ml\smart_allot\artifacts\test_predictions.csv)
- Andhra Pradesh recommendations: [andhra_pradesh_recommendations.csv](C:\Users\S Sameer\Desktop\pds system\ml\smart_allot\artifacts\andhra_pradesh_recommendations.csv)
- Saved model: [smart_allot_model.joblib](C:\Users\S Sameer\Desktop\pds system\ml\smart_allot\artifacts\smart_allot_model.joblib)
- Metrics JSON: [model_metrics.json](C:\Users\S Sameer\Desktop\pds system\ml\smart_allot\artifacts\model_metrics.json)
