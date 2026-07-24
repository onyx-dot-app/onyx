import { formatPeriod } from "@/app/admin/token-rate-limits/TokenRateLimitTables";
import type { TokenRateLimitDisplay } from "@/app/admin/token-rate-limits/types";

function tokenRateLimit(
  periodHours: number,
  tokenBudget: number | null,
  costBudgetCents: number | null
): TokenRateLimitDisplay {
  return {
    token_id: 1,
    enabled: true,
    token_budget: tokenBudget,
    period_hours: periodHours,
    cost_budget_cents: costBudgetCents,
  };
}

test.each([
  ["token-only", tokenRateLimit(24, 1, null), "1 UTC day"],
  ["cost-only", tokenRateLimit(24, null, 100), "1 UTC day"],
  ["dual", tokenRateLimit(48, 1, 100), "2 UTC days"],
])("%s limits display UTC-day windows", (_name, limit, expected) => {
  expect(formatPeriod(limit)).toBe(expected);
});
