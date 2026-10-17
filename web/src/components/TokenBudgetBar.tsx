"use client";

import { useTokenBudget } from "@/lib/tokenBudget";

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function TokenBudgetBar() {
  const { budgetStatus, isLoading } = useTokenBudget();

  if (isLoading || !budgetStatus || !budgetStatus.enabled || !budgetStatus.token_budget) {
    return null;
  }

  const { tokens_used, token_budget, period_hours } = budgetStatus;
  const pct = Math.min(100, Math.round((tokens_used / token_budget) * 100));
  const periodLabel = period_hours === 24 ? "24h" : period_hours === 168 ? "7d" : `${period_hours}h`;

  const barColor =
    pct >= 90 ? "bg-red-500" : pct >= 70 ? "bg-yellow-500" : "bg-green-500";

  return (
    <div className="px-3 py-2.5 border-t border-border">
      <div className="flex items-center justify-between mb-1.5 text-xs text-text-500">
        <span className="font-medium">Token Budget</span>
        <span>{pct}%</span>
      </div>

      <div className="h-1.5 w-full rounded-full bg-background-200 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-300 ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>

      <div className="flex justify-between mt-1 text-xs text-text-400">
        <span>{formatTokens(tokens_used)} used</span>
        <span>{formatTokens(token_budget)} / {periodLabel}</span>
      </div>

      {pct >= 90 && (
        <p className="mt-1.5 text-xs text-red-500">
          Token limit nearly reached
        </p>
      )}
    </div>
  );
}