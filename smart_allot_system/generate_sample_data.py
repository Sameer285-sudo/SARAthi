"""
Generate a realistic sample dataset for SMART-ALLOT.

Output: data/sample_dataset.csv
Rows  : ~4,860  (5 districts × 3 mandals × 3 FPS × 3 commodities × 36 months)
"""

import random
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
rng = np.random.default_rng(SEED)
random.seed(SEED)

DISTRICTS = {
    "Guntur":  ["Rajupalem", "Narasaraopet", "Ponnur"],
    "Nandyal": ["Atmakur",   "Allagadda",    "Srisailam"],
    "Palnadu": ["Macherla",  "Vinukonda",    "Gurazala"],
    "Krishna": ["Machilipatnam", "Vijayawada", "Nuzvid"],
    "Kurnool": ["Nandyal",   "Adoni",        "Yemmiganur"],
}
FPS_PER_MANDAL = 3
COMMODITIES = {
    "Rice":  {"unit_kg": 5, "price_rs": 1},
    "Wheat": {"unit_kg": 3, "price_rs": 2},
    "Sugar": {"unit_kg": 1, "price_rs": 13},
}
MONTHS = pd.date_range("2021-01-01", "2023-12-01", freq="MS")

SEASONAL_IDX = {
    1: 1.08, 2: 1.05, 3: 1.00, 4: 0.96, 5: 0.93,
    6: 0.95, 7: 0.98, 8: 0.99, 9: 1.00, 10: 1.02,
    11: 1.06, 12: 1.10,
}

COMMODITY_BASE = {"Rice": 1.0, "Wheat": 0.55, "Sugar": 0.18}


def make_fps_population(district: str, fps_idx: int) -> int:
    base = {
        "Guntur": 900, "Nandyal": 720, "Palnadu": 840,
        "Krishna": 980, "Kurnool": 790,
    }[district]
    return int(base + fps_idx * 80 + rng.integers(-100, 120))


def utilization_rate(month: int, commodity: str, noise: float) -> float:
    base = {"Rice": 0.88, "Wheat": 0.82, "Sugar": 0.75}[commodity]
    seasonal = SEASONAL_IDX[month]
    return float(np.clip(base * seasonal + noise, 0.45, 1.05))


def generate() -> pd.DataFrame:
    rows = []
    for district, mandals in DISTRICTS.items():
        for mandal in mandals:
            for fps_num in range(1, FPS_PER_MANDAL + 1):
                fps_id = f"FPS-{district[:3].upper()}-{mandal[:3].upper()}-{fps_num:02d}"
                beneficiary_base = make_fps_population(district, fps_num)
                for ts in MONTHS:
                    month_num = ts.month
                    year_num  = ts.year
                    # Beneficiary count grows slightly year-over-year
                    growth = 1.0 + 0.015 * (year_num - 2021)
                    beneficiary_count = int(beneficiary_base * growth + rng.integers(-20, 25))

                    for commodity, meta in COMMODITIES.items():
                        # Entitlement per beneficiary (kg/month)
                        ent_kg = meta["unit_kg"]
                        comm_scale = COMMODITY_BASE[commodity]

                        demand = int(beneficiary_count * ent_kg * comm_scale * SEASONAL_IDX[month_num]
                                     + rng.integers(-40, 50))
                        demand = max(demand, 10)

                        noise = float(rng.normal(0, 0.05))
                        util = utilization_rate(month_num, commodity, noise)
                        stock_allocated = int(demand * rng.uniform(0.90, 1.10))
                        stock_utilized  = int(stock_allocated * util)
                        stock_remaining = max(stock_allocated - stock_utilized, 0)

                        # Inject ~4% missing values
                        if rng.random() < 0.04:
                            stock_utilized  = None
                            stock_remaining = None
                        # Inject ~1% demand spikes (anomalies)
                        if rng.random() < 0.01:
                            demand = int(demand * rng.uniform(2.2, 3.5))

                        rows.append({
                            "date":              ts.strftime("%Y-%m-%d"),
                            "year":              year_num,
                            "month":             month_num,
                            "district":          district,
                            "mandal":            mandal,
                            "fps_id":            fps_id,
                            "commodity":         commodity,
                            "beneficiary_count": beneficiary_count,
                            "demand_kg":         demand,
                            "stock_allocated_kg":stock_allocated,
                            "stock_utilized_kg": stock_utilized,
                            "stock_remaining_kg":stock_remaining,
                            "price_per_kg_rs":   meta["price_rs"],
                            "warehouse":         f"WH-{district[:3].upper()}",
                        })

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


if __name__ == "__main__":
    Path("data").mkdir(exist_ok=True)
    df = generate()
    out = Path("data/sample_dataset.csv")
    df.to_csv(out, index=False)
    print(f"Generated {len(df):,} rows -> {out}")
    print(df.head(3).to_string())
    print("\nColumn dtypes:\n", df.dtypes)
    print(f"\nMissing values:\n{df.isnull().sum()[df.isnull().sum() > 0]}")
