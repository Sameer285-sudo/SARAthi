"""
LangChain agent for intelligent PDS reasoning.

Uses Anthropic Claude (if key is set) with custom tools that call the running
microservices. Falls back to a structured rule-based formatter when no API key
is configured.

Tools available to the Claude agent:
  • get_stock_data(location, commodity)              → SMARTAllot recommendations
  • get_anomaly_data(location, severity)             → Anomaly detection results
  • get_demand_predictions(district, commodity)      → ML GradientBoosting forecasts
  • get_allocation_plan(district, periods)           → LP optimisation results
  • get_system_overview()                            → Dashboard summary

Structured fallback handles all intents without an LLM:
  stock_check, anomaly_check, demand_prediction, allocation_recommendation,
  delivery_status, grievance, entitlement_query, beneficiary_lookup,
  distribution_schedule, fps_location, compliance_check, complaint_fraud,
  general_query, greeting, farewell, help
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

log = logging.getLogger(__name__)

_SVC = {
    "overview":   os.getenv("OVERVIEW_URL",    "http://localhost:8001"),
    "smartallot": os.getenv("SMARTALLOT_URL",  "http://localhost:8002"),
    "anomaly":    os.getenv("ANOMALY_URL",      "http://localhost:8003"),
}

# Commodity token → normalised ML model label (GradientBoosting CSV)
_CMAP: dict[str, str] = {
    "rice":          "Fine Rice",
    "fine rice":     "Fine Rice",
    "fortified rice":"Fine Rice",
    "wheat":         "Atta",
    "atta":          "Atta",
    "flour":         "Atta",
    "sugar":         "Sugar",
    "dal":           "Dal",
    "lentil":        "Dal",
    "pulses":        "Dal",
    "jowar":         "Jowar",
    "sorghum":       "Jowar",
    "raagi":         "Raagi",
    "ragi":          "Raagi",
    "millet":        "Raagi",
    "kerosene":      "Kerosene",
    "oil":           "Oil",
}


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _get(url: str, params: dict | None = None, timeout: float = 8.0) -> dict:
    try:
        r = httpx.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        log.warning("GET %s failed: %s", url, exc)
        return {"error": str(exc)}


def _post(url: str, body: dict, timeout: float = 8.0) -> dict:
    try:
        r = httpx.post(url, json=body, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        log.warning("POST %s failed: %s", url, exc)
        return {"error": str(exc)}


# ── Raw tool functions ────────────────────────────────────────────────────────

def fetch_stock_data(location: str = "", commodity: str = "") -> dict:
    """GET /api/smart-allot/recommendations — fast, reads pre-computed ML CSV."""
    params: dict[str, str] = {}
    if location:  params["district_name"] = location
    if commodity: params["item_name"]     = commodity
    return _get(f"{_SVC['smartallot']}/api/smart-allot/recommendations", params)


def fetch_smartallot_model_info() -> dict:
    """GET SMARTAllot model status/metrics (includes db_demand_model availability)."""
    return _get(f"{_SVC['smartallot']}/api/smart-allot/model-info", timeout=12.0)


def train_db_demand_model() -> dict:
    """POST train the DB demand model from dataset/clean_transactions.csv."""
    return _post(f"{_SVC['smartallot']}/api/smart-allot/train-demand-model", body={}, timeout=60.0)


def fetch_db_demand_forecast(
    *,
    district: str = "",
    afso: str = "",
    fps_id: str = "",
    commodity: str = "",
    periods: int = 3,
) -> dict:
    """POST /api/smart-allot/predict-demand — real DB-backed forecasting pipeline."""
    body = {
        "future_periods": max(1, min(int(periods or 3), 24)),
        "district": district or None,
        "afso": afso or None,
        "fps_id": fps_id or None,
        "commodity": commodity or None,
        "source": "db",
    }
    return _post(f"{_SVC['smartallot']}/api/smart-allot/predict-demand", body=body, timeout=20.0)


def fetch_anomaly_data(location: str = "", severity: str = "", limit: int = 20) -> dict:
    params: dict[str, Any] = {"limit": limit}
    if location: params["location"] = location
    if severity: params["severity"] = severity
    return _get(f"{_SVC['anomaly']}/api/anomaly/anomalies", params)


def fetch_allocation_plan(_district: str = "", periods: int = 3) -> dict:
    body = {"future_periods": max(1, min(periods, 6))}
    return _post(f"{_SVC['smartallot']}/api/smart-allot/optimize-allocation", body)


def fetch_overview() -> dict:
    return _get(f"{_SVC['overview']}/api/overview")


def fetch_alert_summary() -> dict:
    return _get(f"{_SVC['anomaly']}/api/anomaly/summary")


def _norm_commodity(raw: str) -> str:
    return _CMAP.get(raw.strip().lower(), raw.strip())


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are SARATHI — the AI assistant for India's Public Distribution System (PDS) in Andhra Pradesh.
You help administrators, field staff, and citizens with stock levels, demand forecasts, anomalies, and grievances.
You are fluent in English, Telugu, Hindi, Tamil, and Kannada. Always respond in the same language the user wrote in.

Your role: {role}
Conversation context:
{context}

Guidelines:
- Be concise and data-driven. Quote actual numbers from tool results.
- For admins (administrator): full analytics — metrics, predictive alerts, decision-support, KPIs.
- For field_staff: operational data — stock status, delivery tracking, compliance checks.
- For citizens: simple, clear answers — entitlements, FPS location, grievance support.
- Always end with 1–2 actionable suggestions tailored to the role.
- If data shows a problem (anomaly, low stock, delay), flag it prominently.
- Format numbers clearly (e.g., "2,450 kg", "18.5%", "3 months").
- Commodities available: Fine Rice, Atta, Sugar, Dal, Jowar, Raagi.
- Districts with ML data: Annamayya, Chittoor.
"""


# ── LangChain agent (Claude-powered) ─────────────────────────────────────────

class LangChainAgent:
    """
    Wraps LangChain's tool-calling agent with Claude.
    Gracefully degrades to a structured rule-based response when no API key is set.
    """

    def __init__(self) -> None:
        self._ready = False
        self._agent_executor = None
        self._llm = None
        self._try_init()

    def _try_init(self) -> None:
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            log.info("ANTHROPIC_API_KEY not set — using structured fallback")
            return
        try:
            from langchain_anthropic import ChatAnthropic
            from langchain_core.tools import tool
            from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
            from langchain.agents import create_tool_calling_agent, AgentExecutor

            self._llm = ChatAnthropic(
                model="claude-haiku-4-5-20251001",
                api_key=api_key,
                max_tokens=1024,
                temperature=0.2,
            )

            @tool
            def get_stock_data(location: str = "", commodity: str = "") -> str:
                """Fetch SMARTAllot ML recommendations (GradientBoosting, May 2026 forecast).
                location: district name (Annamayya/Chittoor), commodity: Fine Rice/Atta/Sugar/Dal/Jowar/Raagi."""
                data = fetch_stock_data(location, _norm_commodity(commodity))
                recs = data.get("recommendations", [])
                if not recs:
                    return f"No stock data found for {commodity or 'all commodities'} in {location or 'all districts'}."
                total_f = sum(r.get("forecast_next_month", 0) for r in recs)
                total_a = sum(r.get("recommended_allotment", 0) for r in recs)
                lines = [f"Stock Recommendations — {recs[0].get('forecast_for_month','May 2026')} ({len(recs)} records):"]
                lines.append(f"  Total forecast: {total_f:,.0f} kg | Total allotment: {total_a:,.0f} kg")
                for r in recs[:6]:
                    lines.append(
                        f"  • {r.get('district_name','?')} — {r.get('item_name','?')}: "
                        f"forecast {r.get('forecast_next_month',0):,.0f} kg, "
                        f"allotment {r.get('recommended_allotment',0):,.0f} kg, "
                        f"safety stock {r.get('safety_stock',0):,.0f} kg"
                    )
                return "\n".join(lines)

            @tool
            def get_anomaly_data(location: str = "", severity: str = "") -> str:
                """Fetch anomaly detection results. severity: CRITICAL/HIGH/MEDIUM/LOW."""
                data = fetch_anomaly_data(location, severity, limit=10)
                anoms = data.get("anomalies", [])
                summary = fetch_alert_summary()
                total = summary.get("total_anomalies", len(anoms))
                rate  = summary.get("anomaly_rate_pct", 0)
                if not anoms:
                    return f"No anomalies found. Total anomaly rate: {rate:.1f}%."
                lines = [f"Anomalies ({total} total, {rate:.1f}% rate):"]
                for a in anoms[:8]:
                    lines.append(
                        f"  [{a.get('severity','?')}] {a.get('location','?')} — "
                        f"Score: {a.get('anomaly_score',0):.3f}, "
                        f"Delay: {a.get('delivery_delay_hours',0):.1f}h, "
                        f"Mismatch: {a.get('mismatch_pct',0):.1f}%, "
                        f"Reasons: {'; '.join(a.get('reasons',[])[:2])}"
                    )
                return "\n".join(lines)

            @tool
            def get_demand_predictions(district: str = "", commodity: str = "", periods: int = 3) -> str:
                """Fetch real demand forecasts from SMARTAllot (/predict-demand), auto-training if needed."""
                com_norm = commodity.strip()

                info = fetch_smartallot_model_info()
                if "error" in info:
                    return (
                        "Demand forecast service is unavailable (SMARTAllot is down or unreachable).\n"
                        "Start services and verify SMARTAllot is running on port 8002."
                    )

                db_ok = bool(info.get("db_demand_model_available"))
                if not db_ok:
                    trained = train_db_demand_model()
                    if "error" in trained:
                        return (
                            "Demand forecast model is not trained and auto-training failed.\n"
                            f"Reason: {trained.get('error')}\n"
                            "Tip: On Windows, increase paging file / virtual memory if pandas fails to import."
                        )
                    # Refresh info after training
                    info = fetch_smartallot_model_info()

                forecast = fetch_db_demand_forecast(district=district, commodity=com_norm, periods=periods)
                if "error" in forecast:
                    return (
                        "Demand forecast request failed.\n"
                        f"Reason: {forecast.get('error')}"
                    )

                preds = forecast.get("predictions", [])
                if not preds:
                    return "No demand predictions returned for this request."

                total_f = sum(float(p.get("predicted_demand", 0) or 0) for p in preds)
                model_used = preds[0].get("model_used", "unknown")
                lines = [
                    f"Demand Forecast ({periods}-month outlook)",
                    f"District: {district or 'All'} | Commodity: {com_norm or 'All'}",
                    f"Model used: {model_used}",
                    f"Total predicted demand: {total_f:,.0f} kg",
                    "",
                    "Top rows:",
                ]
                for p in preds[:6]:
                    lines.append(
                        f"  • {p.get('location','?')} | {p.get('commodity','?')} | {p.get('date','?')}: "
                        f"{float(p.get('predicted_demand',0) or 0):,.0f} kg "
                        f"(CI {float(p.get('lower_bound',0) or 0):,.0f}–{float(p.get('upper_bound',0) or 0):,.0f})"
                    )

                plots = (info.get("db_demand_model_metrics") or {}).get("plots") or []
                if plots:
                    lines += ["", "Evaluation curves (PNG):"]
                    for fn in plots:
                        lines.append(f"  • {fn}: {_SVC['smartallot']}/api/smart-allot/demand-model/plots/{fn}")

                reg = (info.get("db_demand_model_metrics") or {}).get("regression") or {}
                if reg:
                    mae = reg.get("test_mae")
                    rmse = reg.get("test_rmse")
                    r2 = reg.get("test_r2")
                    lines += ["", f"Regression metrics (test): MAE={mae:.2f} kg, RMSE={rmse:.2f} kg, R²={r2:.4f}"]

                return "\n".join(lines)

            @tool
            def get_allocation_plan(district: str = "", periods: int = 3) -> str:
                """Run LP-based stock allocation optimisation. Returns shortage/overstock risk."""
                data = fetch_allocation_plan(district, periods)
                summary = data.get("summary", {})
                allocs  = data.get("allocations", [])
                if "error" in data or not allocs:
                    return f"Allocation optimizer unavailable: {data.get('error','no data')}."
                lines = [
                    "Allocation Plan (LP Optimisation):",
                    f"  Total predicted demand:  {summary.get('total_predicted_demand',0):>12,.0f} kg",
                    f"  Total recommended:       {summary.get('total_recommended_allocation',0):>12,.0f} kg",
                    f"  Avg shortage risk:       {summary.get('avg_shortage_risk_pct',0):>11.1f}%",
                    f"  Avg overstock risk:      {summary.get('avg_overstock_risk_pct',0):>11.1f}%",
                ]
                for a in allocs[:5]:
                    lines.append(
                        f"  • {a.get('district','?')} / {a.get('fps_id','?')} — "
                        f"{a.get('commodity','?')}: {a.get('recommended_allocation',0):,.0f} kg "
                        f"(shortage risk: {a.get('shortage_risk_pct',0):.1f}%)"
                    )
                return "\n".join(lines)

            @tool
            def get_system_overview() -> str:
                """Fetch a high-level dashboard overview of the entire PDS system."""
                data = fetch_overview()
                smart = data.get("smart_allot", {})
                anom  = data.get("anomalies", {})
                calls = data.get("call_centre", {})
                lines = [
                    "PDS System Overview:",
                    f"  SMARTAllot: {smart.get('total_fps',0)} districts forecasted, "
                    f"total allotment: {smart.get('total_recommended_allotment',0):,.0f} kg",
                    f"  Anomalies:  {anom.get('flagged_shipments',0)} flagged, "
                    f"{anom.get('high_severity',0)} high-severity",
                    f"  Call Centre: {calls.get('open_tickets',0)} open tickets, "
                    f"{calls.get('high_priority_tickets',0)} high-priority",
                ]
                highlights = data.get("operational_highlights", [])
                if highlights:
                    lines.append("  Highlights: " + " | ".join(highlights[:3]))
                return "\n".join(lines)

            tools = [get_stock_data, get_anomaly_data, get_demand_predictions,
                     get_allocation_plan, get_system_overview]

            prompt = ChatPromptTemplate.from_messages([
                ("system", _SYSTEM_PROMPT),
                MessagesPlaceholder("chat_history", optional=True),
                ("human", "{input}"),
                MessagesPlaceholder("agent_scratchpad"),
            ])

            agent = create_tool_calling_agent(self._llm, tools, prompt)
            self._agent_executor = AgentExecutor(
                agent=agent,
                tools=tools,
                verbose=False,
                max_iterations=4,
                handle_parsing_errors=True,
            )
            self._ready = True
            log.info("LangChain agent initialised with Claude + %d tools", len(tools))

        except ImportError as exc:
            log.warning("LangChain/Anthropic not installed (%s) — using structured fallback", exc)
        except Exception as exc:
            log.warning("LangChain init failed (%s) — using structured fallback", exc)

    # ── Public interface ──────────────────────────────────────────────────────

    def run(
        self,
        message: str,
        role: str = "citizen",
        intent: str = "general_query",
        entities: dict | None = None,
        context: str = "",
    ) -> tuple[str, dict]:
        if self._ready and self._agent_executor:
            return self._run_langchain(message, role, intent, entities or {}, context)
        return self._run_structured(intent, entities or {}, role)

    def _run_langchain(
        self, message: str, role: str, intent: str, entities: dict, context: str
    ) -> tuple[str, dict]:
        try:
            from langchain_core.messages import HumanMessage, AIMessage
            chat_history = []
            if context:
                for line in context.strip().split("\n"):
                    if line.startswith("User:"):
                        chat_history.append(HumanMessage(content=line[5:].strip()))
                    elif line.startswith("Assistant:"):
                        chat_history.append(AIMessage(content=line[10:].strip()))

            result = self._agent_executor.invoke({
                "input":        message,
                "role":         role,
                "context":      context or "No prior conversation.",
                "chat_history": chat_history,
            })
            return str(result.get("output", "")), {}
        except Exception as exc:
            log.error("LangChain agent error: %s", exc)
            return self._run_structured(intent, entities, role)

    # ── Structured fallback (no LLM) ─────────────────────────────────────────

    def _run_structured(self, intent: str, entities: dict, role: str) -> tuple[str, dict]:
        """Rule-based fallback — calls microservices and formats results for all intents."""
        location  = entities.get("location", "")
        commodity = entities.get("commodity", "")
        periods   = int(entities.get("future_periods", 3))
        data: dict = {}

        # ── stock_check ────────────────────────────────────────────────────────
        if intent == "stock_check":
            com_norm = _norm_commodity(commodity)
            raw  = fetch_stock_data(location, com_norm)
            data = raw
            recs = raw.get("recommendations", [])
            if not recs:
                text = (
                    f"No stock data found{' for ' + location if location else ''}.\n\n"
                    "Available districts: Annamayya, Chittoor.\n"
                    "Available commodities: Fine Rice, Atta, Sugar, Dal, Jowar, Raagi."
                )
            else:
                total_f = sum(r.get("forecast_next_month", 0) for r in recs)
                total_a = sum(r.get("recommended_allotment", 0) for r in recs)
                month   = recs[0].get("forecast_for_month", "May 2026")
                header  = f"**Stock & Allotment Report — {month}**"
                if com_norm:
                    header += f" | {com_norm}"
                if location:
                    header += f" | {location}"
                lines = [header, "",
                         f"• Total forecast demand:     **{total_f:,.0f} kg**",
                         f"• Total recommended allotment: **{total_a:,.0f} kg**",
                         ""]
                for r in recs[:6]:
                    lines.append(
                        f"  **{r.get('district_name','?')}** — {r.get('item_name','?')}\n"
                        f"    Forecast: {r.get('forecast_next_month',0):,.0f} kg | "
                        f"Allotment: {r.get('recommended_allotment',0):,.0f} kg | "
                        f"Safety stock: {r.get('safety_stock',0):,.0f} kg | "
                        f"Last month: {r.get('last_month_distributed',0):,.0f} kg"
                    )
                if role == "admin":
                    lines += ["", "**Admin Insight:** Forecast uses GradientBoosting (MAE 44.1 kg, WAPE 3.9%). "
                              "Consider pre-positioning stock 7 days before forecast month."]
                text = "\n".join(lines)

        # ── anomaly_check ──────────────────────────────────────────────────────
        elif intent == "anomaly_check":
            raw     = fetch_anomaly_data(location, severity="", limit=10)
            summary = fetch_alert_summary()
            data    = {**raw, "summary": summary}
            anoms   = raw.get("anomalies", [])
            total   = summary.get("total_anomalies", len(anoms))
            rate    = summary.get("anomaly_rate_pct", 0.0)
            critical = [a for a in anoms if a.get("severity") == "CRITICAL"]
            high     = [a for a in anoms if a.get("severity") == "HIGH"]

            if not anoms:
                text = f"No anomalies detected{' in ' + location if location else ''}. Anomaly rate: {rate:.1f}%."
            else:
                top = critical[0] if critical else (high[0] if high else anoms[0])
                lines = [
                    f"**Anomaly Report**{' — ' + location if location else ''}",
                    "",
                    f"• Total anomalies: **{total}** (rate: {rate:.1f}%)",
                    f"• Critical: {len(critical)} | High: {summary.get('high_severity', len(high))}",
                    "",
                    f"**Top Alert — {top.get('location','?')}**",
                    f"• Severity: **{top.get('severity','?')}**",
                    f"• Anomaly score: {top.get('anomaly_score',0):.3f}",
                    f"• Delivery delay: {top.get('delivery_delay_hours',0):.1f} hours",
                    f"• Quantity mismatch: {top.get('mismatch_pct',0):.1f}%",
                    f"• Reason: {'; '.join(top.get('reasons',[])[:2]) or '—'}",
                ]
                if role == "admin" and len(anoms) > 1:
                    lines += ["", f"*{len(anoms)-1} additional flagged transactions. "
                              "Go to Anomaly Detection → Anomalies tab for full list.*"]
                text = "\n".join(lines)

        # ── demand_prediction ──────────────────────────────────────────────────
        elif intent == "demand_prediction":
            # Use real DB-backed forecasting API (not the old precomputed CSV).
            info = fetch_smartallot_model_info()
            if "error" in info:
                data = info
                text = (
                    "Demand forecast service is unavailable (SMARTAllot is down or unreachable).\n\n"
                    "Fix: start services and ensure SMARTAllot is running on `http://localhost:8002`."
                )
            else:
                if not info.get("db_demand_model_available"):
                    trained = train_db_demand_model()
                    if "error" in trained:
                        data = trained
                        text = (
                            "Demand forecast model is not trained and auto-training failed.\n\n"
                            f"Reason: {trained.get('error')}\n\n"
                            "On Windows: increase paging file / virtual memory if pandas DLL import fails."
                        )
                        return text, data
                    info = fetch_smartallot_model_info()

                forecast = fetch_db_demand_forecast(
                    district=location,
                    commodity=commodity.strip(),
                    periods=periods,
                )
                data = {"forecast": forecast, "model_info": info}
                preds = forecast.get("predictions", [])
                if "error" in forecast or not preds:
                    text = (
                        "Demand forecast request failed.\n\n"
                        f"Reason: {forecast.get('error','no predictions')}"
                    )
                else:
                    total_f = sum(float(p.get("predicted_demand", 0) or 0) for p in preds)
                    model_used = preds[0].get("model_used", "unknown")
                    reg = (info.get("db_demand_model_metrics") or {}).get("regression") or {}
                    mae = reg.get("test_mae")
                    rmse = reg.get("test_rmse")
                    r2 = reg.get("test_r2")
                    lines = [
                        f"**Demand Forecast** ({periods}-month outlook)",
                        f"District: **{location or 'All'}** | Commodity: **{commodity or 'All'}**",
                        f"Model: **{model_used}**",
                        f"• Total predicted demand: **{total_f:,.0f} kg**",
                    ]
                    if mae is not None and rmse is not None and r2 is not None:
                        lines.append(f"• Model quality (test): MAE={mae:.2f} kg, RMSE={rmse:.2f} kg, R²={r2:.4f}")

                    lines.append("")
                    for p in preds[:8]:
                        lines.append(
                            f"• {p.get('location','?')} | {p.get('commodity','?')} | {p.get('date','?')}: "
                            f"**{float(p.get('predicted_demand',0) or 0):,.0f} kg** "
                            f"(CI {float(p.get('lower_bound',0) or 0):,.0f}–{float(p.get('upper_bound',0) or 0):,.0f})"
                        )

                    plots = (info.get("db_demand_model_metrics") or {}).get("plots") or []
                    if plots:
                        lines.append("")
                        lines.append("**Evaluation curves (PNG):**")
                        for fn in plots:
                            lines.append(f"• {fn}: {_SVC['smartallot']}/api/smart-allot/demand-model/plots/{fn}")

                    text = "\n".join(lines)

        # ── allocation_recommendation ──────────────────────────────────────────
        elif intent == "allocation_recommendation":
            raw     = fetch_allocation_plan(location, periods)
            data    = raw
            summary = raw.get("summary", {})
            allocs  = raw.get("allocations", [])
            if "error" in raw or not allocs:
                # Fallback: show recommendations from ML CSV as proxy
                rec_raw = fetch_stock_data(location, "")
                recs = rec_raw.get("recommendations", [])
                if recs:
                    total_a = sum(r.get("recommended_allotment", 0) for r in recs)
                    total_f = sum(r.get("forecast_next_month", 0) for r in recs)
                    text = (
                        f"**Allocation Summary** (from ML forecast)\n\n"
                        f"• Total forecast demand:   **{total_f:,.0f} kg**\n"
                        f"• Total recommended:       **{total_a:,.0f} kg**\n\n"
                        "Breakdown:\n" +
                        "\n".join(
                            f"  • {r.get('district_name','?')} — {r.get('item_name','?')}: "
                            f"{r.get('recommended_allotment',0):,.0f} kg"
                            for r in recs[:8]
                        )
                    )
                else:
                    text = ("**Allocation Optimiser** is not trained yet.\n\n"
                            "Go to SMARTAllot → Data & Retrain to run the LP optimisation pipeline.")
            else:
                text = (
                    f"**Allocation Plan — LP Optimisation** ({periods} months)\n\n"
                    f"• Total predicted demand:  **{summary.get('total_predicted_demand',0):,.0f} kg**\n"
                    f"• Total recommended stock: **{summary.get('total_recommended_allocation',0):,.0f} kg**\n"
                    f"• Avg shortage risk:       {summary.get('avg_shortage_risk_pct',0):.1f}%\n"
                    f"• Avg overstock risk:      {summary.get('avg_overstock_risk_pct',0):.1f}%\n\n"
                    f"Top FPS: {allocs[0].get('fps_id','?')} in {allocs[0].get('district','?')} — "
                    f"{allocs[0].get('recommended_allocation',0):,.0f} kg recommended"
                )

        # ── delivery_status ────────────────────────────────────────────────────
        elif intent == "delivery_status":
            txn  = entities.get("transaction_id", "")
            data = {"transaction_id": txn}
            text = (
                f"**Delivery Tracking**{chr(10) + 'Transaction: **' + txn + '**' + chr(10) if txn else chr(10)}\n"
                "Use **Anomaly Detection → Anomalies** tab to look up specific transactions.\n"
                "Filter by transaction ID to see: delivery status, delay hours, quantity mismatch %, and flagging reason.\n\n"
                "**Field Staff tip:** If delivery is delayed >24 hours, raise an anomaly flag immediately."
            )

        # ── grievance ──────────────────────────────────────────────────────────
        elif intent == "grievance":
            data = {"category": "grievance", "role": role}
            if role == "citizen":
                text = (
                    "**Grievance Support**\n\n"
                    "To file a complaint, please provide:\n"
                    "1. Your district and FPS shop ID\n"
                    "2. Nature of issue: short supply / shop closed / card not recognised / expired stock\n"
                    "3. Date and approximate quantity affected\n\n"
                    "Your ticket will be registered with the call centre team (SLA: 48 hours).\n\n"
                    "**Toll-free:** 1967 (PDS Helpline, Andhra Pradesh)"
                )
            else:
                raw   = fetch_overview()
                calls = raw.get("call_centre", {})
                text  = (
                    f"**Grievance Dashboard**\n\n"
                    f"• Open tickets: **{calls.get('open_tickets',0)}**\n"
                    f"• High priority: {calls.get('high_priority_tickets',0)}\n"
                    f"• Languages supported: {', '.join(calls.get('languages_covered', ['Telugu','Hindi','English']))}\n\n"
                    "Go to **Call Centre → Grievances** tab for full ticket management."
                )

        # ── entitlement_query ──────────────────────────────────────────────────
        elif intent == "entitlement_query":
            data = {"category": "entitlement"}
            text = (
                "**Ration Entitlements — Andhra Pradesh PDS**\n\n"
                "Monthly quota per household (Priority Household / AAY):\n\n"
                "| Commodity   | PHH (per unit) | AAY (fixed) |\n"
                "|-------------|---------------|-------------|\n"
                "| Fine Rice   | 5 kg/member   | 35 kg/family|\n"
                "| Atta/Wheat  | 1 kg/member   | 20 kg/family|\n"
                "| Sugar       | 1 kg/family   | 1 kg/family |\n"
                "| Fortified Rice | as per card | as per card |\n\n"
                "**To check your specific entitlement:**\n"
                "• Call helpline: **1967** (toll-free)\n"
                "• Visit your FPS shop with Aadhaar + ration card\n"
                "• Check online: AP Civil Supplies portal\n\n"
                "Need to report a shortage? Ask me to *file a grievance*."
            )

        # ── beneficiary_lookup ─────────────────────────────────────────────────
        elif intent == "beneficiary_lookup":
            card_id = entities.get("transaction_id", "")
            data = {"category": "beneficiary", "card_id": card_id}
            text = (
                f"**Beneficiary Lookup**{chr(10) + 'Card ID: ' + card_id if card_id else ''}\n\n"
                "To look up a beneficiary record:\n"
                "1. Go to **SMARTAllot → Beneficiary Search** (admin panel)\n"
                "2. Enter Aadhaar number or Ration Card number\n"
                "3. Verify household details, FPS assignment, and monthly entitlement\n\n"
                "**Field staff:** Use the offline verification app for on-site checks."
            )

        # ── distribution_schedule ──────────────────────────────────────────────
        elif intent == "distribution_schedule":
            data = {"category": "distribution_schedule"}
            text = (
                "**Distribution Schedule — Andhra Pradesh PDS**\n\n"
                "• Distribution typically runs: **1st–15th of each month**\n"
                "• FPS shops open: Monday–Saturday, 9 AM – 5 PM\n"
                "• Next forecast period: **May 2026**\n\n"
                "Check your local FPS for the exact date. Bring:\n"
                "  ✓ Ration card\n"
                "  ✓ Aadhaar card (for ePoS authentication)\n\n"
                "If your FPS is closed or stock is unavailable, call **1967** or ask me to file a grievance."
            )

        # ── fps_location ───────────────────────────────────────────────────────
        elif intent == "fps_location":
            data = {"category": "fps_location", "location": location}
            text = (
                f"**FPS Shop Locator**{' — ' + location if location else ''}\n\n"
                "To find your nearest Fair Price Shop:\n"
                "• **Online:** Search AP Civil Supplies website with your district/mandal\n"
                "• **SMS:** Send RATION <your ration card number> to 7738299899\n"
                "• **Helpline:** Call 1967 (toll-free, 24×7)\n\n"
                "Your FPS assignment is printed on your ration card. "
                "If you need to change your FPS, contact the DCSO office in your district."
            )

        # ── compliance_check ──────────────────────────────────────────────────
        elif intent == "compliance_check":
            raw     = fetch_anomaly_data(location, severity="", limit=20)
            summary = fetch_alert_summary()
            data    = {**raw, "summary": summary}
            anoms   = raw.get("anomalies", [])
            rate    = summary.get("anomaly_rate_pct", 0.0)
            text = (
                f"**Compliance Report**{' — ' + location if location else ''}\n\n"
                f"• Anomaly rate: **{rate:.1f}%** "
                f"({'⚠️ Above threshold' if rate > 15 else '✅ Within limits'})\n"
                f"• Flagged shipments: {summary.get('flagged_shipments', len(anoms))}\n"
                f"• High-severity issues: {summary.get('high_severity', 0)}\n\n"
                "**KPI Benchmarks:** Anomaly rate < 10% = Compliant | 10–20% = Monitor | >20% = Action required\n\n"
                "Go to **Anomaly Detection → Reports** for the full compliance audit export."
            )
            if role not in ("admin", "field_staff"):
                text = "Compliance reports are available to administrators and field staff only."

        # ── complaint_fraud ────────────────────────────────────────────────────
        elif intent == "complaint_fraud":
            data = {"category": "fraud_complaint"}
            if role == "citizen":
                text = (
                    "**Report Fraud / Corruption**\n\n"
                    "You can report PDS fraud through these channels:\n\n"
                    "1. **Call:** 1967 (PDS Helpline) — Available 24×7\n"
                    "2. **Online:** AP Civil Supplies grievance portal\n"
                    "3. **SMS:** Send FRAUD <details> to 7738299899\n"
                    "4. **App:** mee-Seva app → PDS Grievance\n\n"
                    "Common fraud types to report:\n"
                    "• Ghost beneficiaries (fake ration cards)\n"
                    "• Short supply / weighment fraud\n"
                    "• Black market diversion of PDS stock\n"
                    "• Bribery at FPS shops\n\n"
                    "All reports are **confidential** and acted upon within 7 working days."
                )
            else:
                raw     = fetch_anomaly_data(location, "CRITICAL", limit=10)
                anoms   = raw.get("anomalies", [])
                data    = raw
                if anoms:
                    top = anoms[0]
                    text = (
                        f"**Fraud / Critical Anomaly Report**\n\n"
                        f"• {len(anoms)} critical anomalies detected\n"
                        f"  Top: {top.get('location','?')} — Score {top.get('anomaly_score',0):.3f}\n"
                        f"  Mismatch: {top.get('mismatch_pct',0):.1f}% | "
                        f"Delay: {top.get('delivery_delay_hours',0):.1f}h\n\n"
                        "Escalate to district DCSO and log in the compliance system."
                    )
                else:
                    text = "No critical fraud anomalies detected currently. Monitor Anomaly Detection → CRITICAL tab."

        # ── general_query / greeting / help / fallback ─────────────────────────
        else:
            raw   = fetch_overview()
            data  = raw
            smart = raw.get("smart_allot", {})
            anom  = raw.get("anomalies", {})
            calls = raw.get("call_centre", {})

            if role == "admin":
                text = (
                    f"**PDS360 System Status — Administrator Dashboard**\n\n"
                    f"**SMARTAllot (ML Forecasting)**\n"
                    f"• Districts forecasted: {smart.get('total_fps', 0)}\n"
                    f"• Total recommended allotment: **{smart.get('total_recommended_allotment', 0):,.0f} kg**\n"
                    f"• High-risk locations: {smart.get('high_risk_fps', 0)}\n\n"
                    f"**Anomaly Detection**\n"
                    f"• Flagged shipments: {anom.get('flagged_shipments', 0)}\n"
                    f"• High-severity: {anom.get('high_severity', 0)}\n\n"
                    f"**Call Centre**\n"
                    f"• Open tickets: {calls.get('open_tickets', 0)}\n"
                    f"• High priority: {calls.get('high_priority_tickets', 0)}\n\n"
                    "Ask me about stock, demand forecasts, anomalies, compliance, or allocation."
                )
            elif role == "field_staff":
                text = (
                    f"**PDS Operations Summary — Field Staff**\n\n"
                    f"• Stock allotment pending: {smart.get('total_recommended_allotment', 0):,.0f} kg across {smart.get('total_fps', 0)} locations\n"
                    f"• Anomalies to investigate: {anom.get('flagged_shipments', 0)} ({anom.get('high_severity', 0)} high-severity)\n"
                    f"• Open citizen complaints: {calls.get('open_tickets', 0)}\n\n"
                    "Ask me: stock levels, delivery status, anomalies, or to file a grievance."
                )
            else:
                text = (
                    "**SARATHI — PDS Assistant**\n\n"
                    "I can help you with:\n"
                    "• Your monthly ration entitlement\n"
                    "• FPS shop location and schedule\n"
                    "• Filing a complaint or grievance\n"
                    "• Tracking a delivery\n\n"
                    "Just ask in **English, Telugu, Hindi, Tamil, or Kannada**!\n\n"
                    "Helpline: **1967** (toll-free, 24×7)"
                )

        return text, data

    @property
    def is_llm_ready(self) -> bool:
        return self._ready


# Singleton
langchain_agent = LangChainAgent()
