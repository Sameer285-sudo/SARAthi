# SMART-ALLOT — Smart Allotment & Resource Tracking

AI-powered demand forecasting and optimized allocation for PDS distribution cycles.

## Project Structure

```
smart_allot_system/
├── data/                        # Datasets (generated or uploaded)
│   └── sample_dataset.csv
├── src/                         # Core ML library
│   ├── data_processing.py       # Load, clean, feature engineering, normalization
│   ├── modeling.py              # Ridge Regression baseline + Prophet advanced model
│   ├── optimization.py          # LP-based allocation engine (scipy linprog)
│   ├── anomaly_detection.py     # Z-score + IQR + Isolation Forest + spike detection
│   └── evaluation.py            # MAE, RMSE, MAPE, WAPE, R², time-series CV
├── api/
│   └── main.py                  # FastAPI REST API
├── dashboard/
│   └── app.py                   # Streamlit visual dashboard
├── models/                      # Saved model artifacts (auto-created)
├── generate_sample_data.py      # Generate ~5k-row realistic sample dataset
├── retrain.py                   # CLI retraining pipeline
└── requirements.txt
```

## Quick Start

### 1. Install dependencies

```bash
cd "smart_allot_system"
pip install -r requirements.txt
```

> Prophet requires additional system dependencies on some platforms:
> - Windows: `pip install pystan==2.19.1.1` before installing prophet
> - Linux/Mac: `pip install prophet` usually works directly

### 2. Generate sample data

```bash
python generate_sample_data.py
```

Produces `data/sample_dataset.csv` (~4,860 rows, 5 districts, 45 FPS, 3 commodities, 36 months).

### 3. Train models

```bash
python retrain.py --data data/sample_dataset.csv --test-months 3
```

Saves to `models/`: baseline.pkl, prophet/, anomaly_detector.pkl, scaler.pkl, eval_report.json.

### 4A. Launch Streamlit Dashboard

```bash
streamlit run dashboard/app.py
```

Opens at http://localhost:8501

### 4B. Launch FastAPI

```bash
uvicorn api.main:app --reload --port 8001
```

API docs at http://localhost:8001/docs

---

## REST API Reference

### `POST /upload-data`
Upload CSV/Excel dataset. Runs preprocessing automatically.

```bash
curl -X POST http://localhost:8001/upload-data \
  -F "file=@data/sample_dataset.csv" \
  -F "auto_retrain=false"
```

### `POST /predict-demand`
Predict demand for future months.

```bash
curl -X POST http://localhost:8001/predict-demand \
  -H "Content-Type: application/json" \
  -d '{"future_periods": 3, "district": "Guntur", "commodity": "Rice"}'
```

**Response:**
```json
{
  "predictions": [
    {
      "location": "Guntur",
      "district": "Guntur",
      "commodity": "Rice",
      "date": "2024-01-01",
      "predicted_demand": 12450.5,
      "lower_bound": 11205.0,
      "upper_bound": 13696.0,
      "confidence_score": 0.87,
      "model_used": "Prophet"
    }
  ]
}
```

### `POST /optimize-allocation`
Generate LP-optimized allocation recommendations.

```bash
curl -X POST http://localhost:8001/optimize-allocation \
  -H "Content-Type: application/json" \
  -d '{
    "future_periods": 3,
    "total_supply": {"Rice": 500000, "Wheat": 200000},
    "shortage_weight": 3.0,
    "overstock_weight": 1.0,
    "safety_buffer_pct": 0.10
  }'
```

**Response:**
```json
{
  "summary": {
    "total_predicted_demand": 485000.0,
    "total_recommended_allocation": 498000.0,
    "avg_shortage_risk_pct": 2.1,
    "avg_overstock_risk_pct": 5.3
  },
  "allocations": [
    {
      "location": "Guntur / FPS-GUN-RAJ-01",
      "district": "Guntur",
      "commodity": "Rice",
      "predicted_demand": 4500.0,
      "recommended_allocation": 4950.0,
      "confidence_score": 0.87,
      "shortage_risk_pct": 0.0,
      "overstock_risk_pct": 10.0,
      "allocation_method": "LP"
    }
  ]
}
```

### `GET /anomalies`
Detect anomalous demand records.

```bash
curl "http://localhost:8001/anomalies?district=Guntur&severity=HIGH&limit=20"
```

### `POST /retrain`
Trigger full retraining on loaded dataset.

```bash
curl -X POST http://localhost:8001/retrain \
  -H "Content-Type: application/json" \
  -d '{"test_months": 3}'
```

### `GET /model-info`
Model metadata and evaluation report.

### `GET /health`
System health check.

---

## Dataset Schema

| Column | Type | Description |
|--------|------|-------------|
| date | date | Year-month (e.g. 2023-01-01) |
| district | string | District name |
| mandal | string | Mandal name |
| fps_id | string | Fair Price Shop ID |
| commodity | string | Rice / Wheat / Sugar |
| beneficiary_count | int | Number of beneficiaries |
| demand_kg | float | Actual/estimated demand in kg |
| stock_allocated_kg | float | Stock allocated by government |
| stock_utilized_kg | float | Stock actually distributed |
| stock_remaining_kg | float | Unsold/unused stock |
| price_per_kg_rs | float | Subsidized price (₹/kg) |
| warehouse | string | Source warehouse code |

---

## ML Architecture

### Feature Engineering
- Lag features: demand at T-1, T-3, T-6, T-12 months
- Rolling stats: 3m / 6m / 12m rolling mean and std
- Seasonal encoding: month sin/cos, seasonal index per month
- Growth rate: month-on-month % change
- Beneficiary-demand ratio

### Models
| Model | Algorithm | Use Case |
|-------|-----------|----------|
| Baseline | Ridge Regression | Fast, interpretable, FPS-level |
| Advanced | Facebook Prophet | District-level seasonal forecasting |

### Optimization
Linear Programming via `scipy.optimize.linprog` (HiGHS solver):
- Minimizes: `shortage_weight × shortage + overstock_weight × overstock`
- Constraints: total supply limit, min/max per-location bounds
- Fallback: proportional heuristic if LP is infeasible

### Anomaly Detection
| Method | Detects |
|--------|---------|
| Z-Score | Statistical outliers per FPS × commodity |
| IQR | Extreme distribution outliers |
| Isolation Forest | Multivariate anomalies (demand + utilization + growth) |
| Spike Detection | Sudden N× jump vs rolling average |

---

## Evaluation Metrics

| Metric | Description |
|--------|-------------|
| MAE | Mean Absolute Error (kg) |
| RMSE | Root Mean Squared Error (kg) |
| MAPE | Mean Absolute Percentage Error |
| WAPE | Weighted Absolute Percentage Error |
| R² | Coefficient of determination |
| Bias | Systematic over/under-prediction |

---

## Dashboard Pages

| Page | Features |
|------|---------|
| Data Overview | Upload, stats, missing values, district breakdown |
| Trend Analysis | Time-series by district/mandal/FPS, seasonal patterns, utilization |
| Demand Forecast | Historical + future forecast chart, confidence intervals, eval metrics |
| Allocation Plan | LP optimization with supply constraints, risk heatmap, downloadable plan |
| Anomaly Detection | Flagged records, severity pie chart, anomaly scatter plot |
