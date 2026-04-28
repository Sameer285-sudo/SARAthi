import React from "react";
import { Zap } from "lucide-react";

export type SarathiInsightSection = {
  heading: string;
  body: React.ReactNode;
};

export function SarathiInsightsCard({
  title = "SARATHI AI Insights",
  sections,
  variant = "full",
}: {
  title?: string;
  sections: SarathiInsightSection[];
  variant?: "full" | "compact";
}) {
  const pad = variant === "compact" ? "14px" : "24px";
  const radius = variant === "compact" ? "16px" : "20px";
  const titleSize = variant === "compact" ? "1.0rem" : "1.2rem";
  const iconSize = variant === "compact" ? 18 : 24;
  const gap = variant === "compact" ? "12px" : "16px";

  return (
    <div
      style={{
        background: "var(--insights-gradient)",
        borderRadius: radius,
        padding: pad,
        color: "white",
        boxShadow: "0 10px 30px rgba(30,58,138,0.25)",
        position: "relative",
        overflow: "hidden",
      }}
    >
      {variant === "full" && (
        <div style={{ position: "absolute", right: -20, top: -20, opacity: 0.1 }}>
          <Zap size={140} />
        </div>
      )}

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "10px",
          marginBottom: variant === "compact" ? "12px" : "20px",
          zIndex: 1,
          position: "relative",
        }}
      >
        <Zap size={iconSize} color="var(--insights-accent)" />
        <h3 style={{ margin: 0, fontSize: titleSize, fontWeight: 700 }}>{title}</h3>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap, zIndex: 1, position: "relative" }}>
        {sections.map((s, idx) => (
          <div
            key={`${s.heading}-${idx}`}
            style={{
              background: "var(--insights-surface)",
              borderRadius: "12px",
              padding: variant === "compact" ? "12px" : "16px",
              lineHeight: 1.45,
            }}
          >
            <strong
              style={{
                display: "block",
                color: "var(--insights-accent)",
                marginBottom: "4px",
                fontSize: variant === "compact" ? "0.78rem" : "0.85rem",
                letterSpacing: "0.06em",
              }}
            >
              {s.heading.toUpperCase()}
            </strong>
            <div style={{ fontSize: variant === "compact" ? "0.85rem" : "0.95rem" }}>{s.body}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
