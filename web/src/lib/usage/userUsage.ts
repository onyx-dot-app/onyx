"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";

export interface UsageExportTotals {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cost_cents: number;
}

export interface UsageExportUser {
  email: string;
  totals: UsageExportTotals;
}

export interface UsageExportResponse {
  start: string;
  end: string;
  users: UsageExportUser[];
}

/**
 * Company-wide per-user usage (admin). GET /api/admin/usage/export.
 * Mutate the returned `refetch` after a reset to revalidate the table.
 */
export function useUsageExport() {
  const { data, error, isLoading, mutate } = useSWR<UsageExportResponse>(
    SWR_KEYS.adminUsageExport,
    errorHandlingFetcher,
    { revalidateOnFocus: false },
  );

  return { usage: data, isLoading, error, refetch: mutate };
}

/**
 * Clears a user's current-window usage to lift a budget block (prior windows
 * are preserved). POST /api/admin/usage/reset.
 * @throws Error with the API detail message on failure.
 */
export async function resetUserUsage(userEmail: string): Promise<void> {
  const response = await fetch(SWR_KEYS.adminUsageReset, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_email: userEmail }),
  });

  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(data?.detail || data?.error_code || response.statusText);
  }
}
