import useSWR from "swr";

interface TokenBudget {
  budget_cents: number | null;
  budget_remaining_cents: number | null;
  budget_period_hours: number | null;
  window_cost_cents: number;
}

const fetcher = (url: string) =>
  fetch(url).then((r) => {
    if (!r.ok) throw new Error("failed");
    return r.json();
  });

export function useTokenBudget() {
  const { data, error } = useSWR<TokenBudget>(
    "/api/user/usage",
    fetcher,
    { refreshInterval: 60_000 }
  );

  const hasBudget =
    data?.budget_cents != null && data.budget_cents > 0;

  const percentageUsed =
    hasBudget && data!.budget_remaining_cents != null
      ? Math.min(
          100,
          ((data!.budget_cents! - data!.budget_remaining_cents!) /
            data!.budget_cents!) *
            100
        )
      : null;

  return {
    hasBudget,
    percentageUsed,
    budgetCents: data?.budget_cents ?? null,
    remainingCents: data?.budget_remaining_cents ?? null,
    periodHours: data?.budget_period_hours ?? null,
    isLoading: !data && !error,
  };
}