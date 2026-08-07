"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { buildApiPath } from "@/lib/urlBuilder";

export interface UsageExportTotals {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cost_cents: number;
}

export interface UsageExportUser {
  email: string;
  totals: UsageExportTotals;
  records: UsageExportRecord[];
}

export interface UsageExportRecord {
  model: string;
  flow?: string;
  provider?: string;
  day: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cost_cents: number;
}

export interface UsageExportResponse {
  start: string;
  end: string;
  users: UsageExportUser[];
}

function formatDateParam(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

export function useUsageExport(range?: { from: Date; to: Date } | undefined) {
  const url = buildApiPath(SWR_KEYS.adminUsageExport, {
    start: range?.from ? formatDateParam(range.from) : undefined,
    end: range?.to ? formatDateParam(range.to) : undefined,
  });
  const { data, error, isLoading, mutate } = useSWR<UsageExportResponse>(
    url,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );

  return { usage: data, isLoading, error, refetch: mutate };
}

/** Clears a user's usage across active enforcement windows. */
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
