import useSWR from "swr";
import { errorHandlingFetcher, skipRetryOnAuthError } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";

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
  // The user's cost budget, what's left, and its window in hours (for the
  // "per week/day/hour" label). All null when no cost limit applies.
  budget_cents: number | null;
  budget_remaining_cents: number | null;
  budget_period_hours: number | null;
  selected_model_price: SelectedModelPrice | null;
}

export function useUserUsage(days: number) {
  return useSWR<UserUsageResponse>(SWR_KEYS.userUsage(days), errorHandlingFetcher, {
    revalidateOnFocus: false,
    onErrorRetry: skipRetryOnAuthError,
  });
}
