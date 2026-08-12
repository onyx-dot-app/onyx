"use client";

import { useTokenBudget } from "@/hooks/useTokenBudget";

export function TokenBudgetIndicator() {
  const { hasBudget, percentageUsed, remainingCents, budgetCents, periodHours, isLoading } =
    useTokenBudget();

  if (isLoading || !hasBudget || percentageUsed === null) return null;

  const pctUsed = Math.round(percentageUsed);
  const pctRemaining = 100 - pctUsed;

  const color =
    pctUsed >= 90
      ? "var(--destructive, #ef4444)"
      : pctUsed >= 75
      ? "#f59e0b"
      : "#22c55e";

  const formatCents = (cents: number) =>
    cents >= 100
      ? `$${(cents / 100).toFixed(2)}`
      : `${cents.toFixed(1)}¢`;

  const tooltipText = [
    `${formatCents(budgetCents! - remainingCents!)} used of ${formatCents(budgetCents!)}`,
    `Resets every ${periodHours}h`,
  ].join(" · ");

  return (
    <div
      title={tooltipText}
      style={{
        padding: "8px 12px",
        display: "flex",
        flexDirection: "column",
        gap: "5px",
        cursor: "default",
        userSelect: "none",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontSize: "11px",
          color: "var(--muted-foreground)",
        }}
      >
        <span>Token budget</span>
        <span style={{ color, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
          {pctRemaining}% left
        </span>
      </div>

      <div
        style={{
          height: "4px",
          borderRadius: "2px",
          background: "var(--border)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pctUsed}%`,
            height: "100%",
            background: color,
            borderRadius: "2px",
            transition: "width 0.5s ease, background 0.3s ease",
          }}
        />
      </div>

      {pctUsed >= 75 && (
        <span style={{ fontSize: "11px", color, fontWeight: 500 }}>
          {pctUsed >= 90 ? "⚠ Budget almost exhausted" : "Budget filling up"}
        </span>
      )}
    </div>
  );
}