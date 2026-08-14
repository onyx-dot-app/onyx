"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { buildApiPath } from "@/lib/urlBuilder";
import { formatDateForApiParam } from "@/lib/dateUtils";

export interface UsageExportTotals {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
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
  cache_creation_tokens: number;
  cost_cents: number;
}

export interface UsageExportResponse {
  start: string;
  end: string;
  users: UsageExportUser[];
}

export function useUsageExport(range?: { from: Date; to: Date } | undefined) {
  const url = buildApiPath(SWR_KEYS.adminUsageExport, {
    start: range?.from ? formatDateForApiParam(range.from) : undefined,
    end: range?.to ? formatDateForApiParam(range.to) : undefined,
  });
  const { data, error, isLoading, mutate } = useSWR<UsageExportResponse>(
    url,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );

  return { usage: data, isLoading, error, refetch: mutate };
}
