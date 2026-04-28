/**
 * HierarchicalFilterBar — reusable cascading filter bar.
 * District → AFSO → FPS → Month → Commodity
 * Used by: OverviewPage, SmartAllotPage, ModelOverviewPage, AnomaliesPage, DistributionPage.
 */
import { ChevronDown, Filter, RefreshCw } from "lucide-react";
import type { TxFilters } from "../api";

interface FilterOptions {
  districts:   string[];
  afsos:       string[];
  fpsList:     string[];
  months:      string[];
  commodities: string[];
}

interface HierarchicalFilterBarProps {
  filters:       TxFilters;
  filterOptions: FilterOptions;
  onFilterChange: (key: keyof TxFilters, val: string) => void;
  onReset:       () => void;
  /** Which fields to show. Defaults to all 5. */
  show?: Array<"district" | "afso" | "fps_id" | "month" | "commodity">;
  /** Compact (less padding) mode */
  compact?: boolean;
}

function FSelect({
  label, value, options, onChange, disabled = false,
}: {
  label: string; value: string; options: string[];
  onChange: (v: string) => void; disabled?: boolean;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 150 }}>
      <label style={{
        fontSize: "0.72rem", fontWeight: 700, color: "var(--muted)",
        textTransform: "uppercase", letterSpacing: "0.06em",
      }}>
        {label}
      </label>
      <div style={{ position: "relative" }}>
        <select
          value={value}
          disabled={disabled || options.length === 0}
          onChange={e => onChange(e.target.value)}
          style={{
            appearance: "none", width: "100%", padding: "8px 32px 8px 11px",
            borderRadius: 9, border: "1.5px solid var(--line)",
            background: disabled ? "var(--control-glass-disabled)" : "var(--control-glass)",
            color: "var(--text)", fontSize: "0.86rem", fontWeight: 500,
            cursor: disabled ? "not-allowed" : "pointer",
            outline: "none", transition: "border 0.15s",
            boxShadow: "0 10px 24px rgba(30,134,214,0.06)",
          }}
        >
          <option value="">All {label}s</option>
          {options.map(o => <option key={o} value={o}>{o}</option>)}
        </select>
        <ChevronDown size={13} style={{
          position: "absolute", right: 9, top: "50%",
          transform: "translateY(-50%)", pointerEvents: "none", color: "var(--muted)",
        }} />
      </div>
    </div>
  );
}

export function HierarchicalFilterBar({
  filters, filterOptions, onFilterChange, onReset,
  show = ["district", "afso", "fps_id", "month", "commodity"],
  compact = false,
}: HierarchicalFilterBarProps) {
  const p = compact ? "14px 18px" : "16px 22px";
  return (
    <div style={{
      background: "var(--card-glass)", borderRadius: 14, padding: p,
      boxShadow: "var(--shadow-soft, 0 2px 12px rgba(0,0,0,0.06))",
      border: "1px solid var(--line)",
      backdropFilter: "blur(12px)",
      display: "flex", flexWrap: "wrap", gap: 14, alignItems: "flex-end",
    }}>
      <div style={{ color: "var(--navy)", display: "flex", alignItems: "center", gap: 6, fontWeight: 700, fontSize: "0.88rem" }}>
        <Filter size={15} /> Filters
      </div>

      {show.includes("district") && (
        <FSelect
          label="District" value={filters.district ?? ""}
          options={filterOptions.districts}
          onChange={v => onFilterChange("district", v)}
        />
      )}
      {show.includes("afso") && (
        <FSelect
          label="AFSO" value={filters.afso ?? ""}
          options={filterOptions.afsos}
          onChange={v => onFilterChange("afso", v)}
          disabled={!filters.district && filterOptions.afsos.length > 20}
        />
      )}
      {show.includes("fps_id") && (
        <FSelect
          label="FPS" value={filters.fps_id ?? ""}
          options={filterOptions.fpsList.slice(0, 200)}
          onChange={v => onFilterChange("fps_id", v)}
          disabled={!filters.afso}
        />
      )}
      {show.includes("month") && (
        <FSelect
          label="Month" value={filters.month ?? ""}
          options={filterOptions.months}
          onChange={v => onFilterChange("month", v)}
        />
      )}
      {show.includes("commodity") && (
        <FSelect
          label="Commodity" value={filters.commodity ?? ""}
          options={filterOptions.commodities}
          onChange={v => onFilterChange("commodity", v)}
        />
      )}

      <button
        onClick={onReset}
        style={{
          display: "flex", alignItems: "center", gap: 5,
          padding: "8px 13px", borderRadius: 9,
          border: "1.5px solid var(--line)", background: "var(--control-glass)",
          color: "var(--muted)", fontWeight: 600, fontSize: "0.82rem",
          cursor: "pointer", marginBottom: 0,
        }}
      >
        <RefreshCw size={13} /> Reset
      </button>
    </div>
  );
}
