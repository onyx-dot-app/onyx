import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";

export interface TokenBudgetStatus {
  tokens_used: number;
  token_budget: number | null;
  period_hours: number;
  enabled: boolean;
}

export function useTokenBudget() {
  const { data, error, isLoading } = useSWR<TokenBudgetStatus>(
    "/api/token-budget",
    errorHandlingFetcher,
    { refreshInterval: 60_000 }
  );

  return {
    budgetStatus: data ?? null,
    isLoading,
    isError: !!error,
  };
}