# SMARTAllot ML Pipeline

This module cleans the provided PDS allocation/distribution dataset, aggregates duplicate district-month records, trains a forecasting model, evaluates it, and generates allotment recommendations for Andhra Pradesh.

## Approach

- Cleans date, district, and numeric fields
- Restores missing district names using `state_name + district_code`
- Aggregates duplicate `state + district + month` records by summing quantities
- Builds a district-level monthly panel
- Forecasts next month's effective demand using a global gradient-boosted model with:
  - lag features
  - rolling averages and volatility
  - seasonal features
  - geographic categorical features
- Generates `SMARTAllot` recommendations using:
  - forecast demand
  - carryover stock proxy
  - safety stock based on forecast volatility

## Target

The target is `effective_qty_distributed`, defined as:

- `total_qty_distributed_epos` when available and positive
- otherwise `total_qty_distributed_unautomated + total_qty_distributed_automated`

This is the best proxy in the dataset for actual beneficiary drawal / realized demand.

## Outputs

The training script writes:

- `artifacts/cleaned_panel.csv`
- `artifacts/train_dataset.csv`
- `artifacts/model_metrics.json`
- `artifacts/andhra_pradesh_recommendations.csv`
- `artifacts/smart_allot_model.joblib`

## Run

```powershell
python .\ml\smart_allot\train_smart_allot.py --data "C:\Users\S Sameer\Desktop\pds system\dataset\a2a38535-2208-407b-9e5a-afe2e00088f1.csv"
```
