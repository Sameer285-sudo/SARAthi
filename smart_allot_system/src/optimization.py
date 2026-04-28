"""
Optimization engine for SMART-ALLOT.

Allocates available stock across locations to minimize:
  - Shortage penalty  (weight: shortage_weight)
  - Overstocking cost (weight: overstock_weight)
  - Wastage cost      (perishable surplus)

Uses scipy.optimize.linprog (LP) for exact allocation, with a
heuristic proportional fallback when LP is infeasible.

Output schema per location:
  {
    location, district, mandal, fps_id, commodity, date,
    predicted_demand, recommended_allocation, confidence_score,
    shortage_risk_pct, overstock_risk_pct, allocation_method
  }
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import linprog

log = logging.getLogger(__name__)


# ── Config ─────────────────────────────────────────────────────────────────────

@dataclass
class AllocationConfig:
    shortage_weight:    float = 3.0    # Penalty per unit short (higher = prefer avoiding shortage)
    overstock_weight:   float = 1.0    # Cost per unit over-allocated
    wastage_weight:     float = 0.5    # Extra cost for perishable surplus beyond buffer
    safety_buffer_pct:  float = 0.10   # % above predicted demand as safety stock
    max_overstock_pct:  float = 0.25   # Never allocate more than 125% of predicted demand
    min_allocation_pct: float = 0.70   # Always allocate at least 70% of predicted demand


DEFAULT_CONFIG = AllocationConfig()


# ── Result container ───────────────────────────────────────────────────────────

@dataclass
class AllocationResult:
    location:              str
    district:              str
    mandal:                str
    fps_id:                str
    commodity:             str
    date:                  str
    predicted_demand:      float
    recommended_allocation:float
    confidence_score:      float
    shortage_risk_pct:     float
    overstock_risk_pct:    float
    allocation_method:     str   # "LP" | "heuristic"


# ── Core LP solver ─────────────────────────────────────────────────────────────

def _solve_lp(
    demands: np.ndarray,
    total_supply: float,
    cfg: AllocationConfig,
) -> tuple[np.ndarray, str]:
    """
    LP formulation:
      Variables x[i] = allocation to location i

      Minimise:  sum_i [ shortage_weight * s_i + overstock_weight * o_i ]
      Where:
        s_i = max(demand_i - x_i, 0)   (shortage, linearised)
        o_i = max(x_i - demand_i, 0)   (overstock, linearised)

    Equivalent to minimising:
      c^T z where z = [x; s; o]

    Subject to:
      sum(x) <= total_supply
      x_i + s_i >= demand_i              (define shortage)
      x_i - o_i <= demand_i              (define overstock)
      min_alloc_i <= x_i <= max_alloc_i
      s_i >= 0, o_i >= 0
    """
    n = len(demands)
    min_alloc = demands * cfg.min_allocation_pct
    max_alloc = demands * (1 + cfg.max_overstock_pct)
    # Adjustment: use demand + safety buffer as target
    targets = demands * (1 + cfg.safety_buffer_pct)

    # Variables: [x_0..x_{n-1}, s_0..s_{n-1}, o_0..o_{n-1}]
    # Objective: minimise shortage + overstock cost
    c = np.concatenate([
        np.zeros(n),
        np.full(n, cfg.shortage_weight),
        np.full(n, cfg.overstock_weight),
    ])

    # Inequality constraints (A_ub @ z <= b_ub):
    # 1. sum(x) <= total_supply
    row_supply      = np.zeros(3 * n)
    row_supply[:n]  = 1.0

    # 2. x_i - o_i <= demand_i  →  x_i + 0*s_i - o_i <= demand_i
    A_over = np.zeros((n, 3 * n))
    for i in range(n):
        A_over[i, i]     =  1.0
        A_over[i, 2*n+i] = -1.0

    # 3. -x_i - s_i <= -demand_i  →  x_i + s_i >= demand_i
    A_short = np.zeros((n, 3 * n))
    for i in range(n):
        A_short[i, i]   = -1.0
        A_short[i, n+i] = -1.0

    A_ub = np.vstack([row_supply.reshape(1, -1), A_over, A_short])
    b_ub = np.concatenate([[total_supply], demands, -demands])

    # Bounds
    x_bounds = [(min_alloc[i], max_alloc[i]) for i in range(n)]
    s_bounds  = [(0, None)] * n
    o_bounds  = [(0, None)] * n
    bounds    = x_bounds + s_bounds + o_bounds

    result = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs")

    if result.success:
        return result.x[:n], "LP"

    # LP failed → proportional heuristic
    log.warning("LP infeasible (%s) — using proportional heuristic.", result.message)
    return _heuristic_allocate(demands, total_supply, cfg), "heuristic"


def _heuristic_allocate(
    demands: np.ndarray,
    total_supply: float,
    cfg: AllocationConfig,
) -> np.ndarray:
    """Proportional allocation with safety buffer; scaled if supply < total demand."""
    targets = demands * (1 + cfg.safety_buffer_pct)
    total_target = targets.sum()
    if total_target == 0:
        return np.zeros_like(demands)

    if total_supply >= total_target:
        return np.clip(targets, demands * cfg.min_allocation_pct, demands * (1 + cfg.max_overstock_pct))

    scale = total_supply / total_target
    alloc = targets * scale
    return np.clip(alloc, demands * cfg.min_allocation_pct, demands * (1 + cfg.max_overstock_pct))


# ── Risk metrics ───────────────────────────────────────────────────────────────

def _shortage_risk(demand: float, allocation: float) -> float:
    if demand <= 0:
        return 0.0
    return round(max(0.0, (demand - allocation) / demand * 100), 1)


def _overstock_risk(demand: float, allocation: float) -> float:
    if demand <= 0:
        return 0.0
    return round(max(0.0, (allocation - demand) / demand * 100), 1)


# ── Public API ─────────────────────────────────────────────────────────────────

def optimize_allocation(
    forecast_df: pd.DataFrame,
    total_supply_by_commodity: Optional[dict[str, float]] = None,
    cfg: AllocationConfig = DEFAULT_CONFIG,
) -> list[AllocationResult]:
    """
    Main entry point.

    forecast_df columns (required):
        district, mandal, fps_id, commodity, date,
        predicted_demand, confidence_score
        (optional: location)

    total_supply_by_commodity: e.g. {"Rice": 500000, "Wheat": 200000}
        If None, assumes unlimited supply (allocation = demand × buffer).

    Returns a list of AllocationResult.
    """
    results: list[AllocationResult] = []

    commodities = forecast_df["commodity"].unique()

    for commodity in commodities:
        sub = forecast_df[forecast_df["commodity"] == commodity].copy()
        if sub.empty:
            continue

        demands = sub["predicted_demand"].values.astype(float)
        demands = np.where(demands < 0, 0, demands)

        total_supply = (
            total_supply_by_commodity.get(commodity, float("inf"))
            if total_supply_by_commodity
            else float("inf")
        )

        if total_supply == float("inf"):
            # No constraint — give everyone demand + buffer
            allocations = demands * (1 + cfg.safety_buffer_pct)
            method = "heuristic"
        else:
            allocations, method = _solve_lp(demands, total_supply, cfg)

        allocations = np.round(allocations, 1)

        for i, (_, row) in enumerate(sub.iterrows()):
            demand = float(demands[i])
            alloc  = float(allocations[i])
            results.append(AllocationResult(
                location=row.get("location", f"{row.get('district', '')} / {row.get('fps_id', '')}"),
                district=row.get("district", ""),
                mandal=row.get("mandal", ""),
                fps_id=row.get("fps_id", ""),
                commodity=commodity,
                date=str(row.get("date", "")),
                predicted_demand=round(demand, 1),
                recommended_allocation=alloc,
                confidence_score=round(float(row.get("confidence_score", 0.75)), 3),
                shortage_risk_pct=_shortage_risk(demand, alloc),
                overstock_risk_pct=_overstock_risk(demand, alloc),
                allocation_method=method,
            ))

    return results


def results_to_dataframe(results: list[AllocationResult]) -> pd.DataFrame:
    return pd.DataFrame([asdict(r) for r in results])


# ── District-level aggregation ─────────────────────────────────────────────────

def aggregate_to_district(results: list[AllocationResult]) -> pd.DataFrame:
    """Aggregate FPS-level allocations up to district × commodity × date."""
    df = results_to_dataframe(results)
    if df.empty:
        return df
    return (
        df.groupby(["district", "commodity", "date"], as_index=False)
          .agg(
              total_predicted_demand=("predicted_demand", "sum"),
              total_recommended_allocation=("recommended_allocation", "sum"),
              avg_confidence=("confidence_score", "mean"),
              fps_count=("fps_id", "nunique"),
          )
    )


# ── Supply constraint calculator ───────────────────────────────────────────────

def estimate_required_supply(
    forecast_df: pd.DataFrame,
    cfg: AllocationConfig = DEFAULT_CONFIG,
) -> dict[str, float]:
    """
    Estimates the minimum total supply needed to satisfy all predicted demands
    with safety buffer.
    """
    out: dict[str, float] = {}
    for commodity, grp in forecast_df.groupby("commodity"):
        total = grp["predicted_demand"].sum() * (1 + cfg.safety_buffer_pct)
        out[str(commodity)] = round(float(total), 1)
    return out
