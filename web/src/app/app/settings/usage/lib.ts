import useSWR from "swr";
import { errorHandlingFetcher, skipRetryOnAuthError } from "@/lib/fetcher";

export interface UsagePerDayByModel {
  day: string; // "YYYY-MM-DD"
  model: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cost_cents: number;
}

export interface SelectedModelPrice {
  input_per_mtok: number | null; // $/1M tokens; null if the model is unpriced
  output_per_mtok: number | null;
}

export interface UserUsageResponse {
  per_day_by_model: UsagePerDayByModel[];
  window_cost_cents: number;
  // null until P5 enforcement ships — render gracefully.
  budget_cents: number | null;
  budget_remaining_cents: number | null;
  selected_model_price: SelectedModelPrice | null;
}

export function usageKey(days: number): string {
  return `/api/user/usage?days=${days}`;
}

export function useUserUsage(days: number) {
  return useSWR<UserUsageResponse>(usageKey(days), errorHandlingFetcher, {
    revalidateOnFocus: false,
    onErrorRetry: skipRetryOnAuthError,
  });
}
