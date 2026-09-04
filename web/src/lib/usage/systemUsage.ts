"use client";

import useSWR from "swr";
import { formatDateForApiParam } from "@/lib/dateUtils";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { buildApiPath } from "@/lib/urlBuilder";
import type { UsageExportTotals } from "@/lib/usage/userUsage";

export type SystemUsageAttribution = "ATTRIBUTED" | "UNATTRIBUTED";

export interface SystemUsageRecord {
  attribution: SystemUsageAttribution;
  model: string;
  flow: string;
  provider: string;
  day: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  cost_cents: number;
}

export interface SystemUsageCategory {
  category: string;
  totals: UsageExportTotals;
  records: SystemUsageRecord[];
}

export interface SystemUsageResponse {
  start: string;
  end: string;
  categories: SystemUsageCategory[];
}

export function useSystemUsage(range?: { from: Date; to: Date }) {
  const url = buildApiPath(SWR_KEYS.adminSystemUsage, {
    start: range?.from ? formatDateForApiParam(range.from) : undefined,
    end: range?.to ? formatDateForApiParam(range.to) : undefined,
  });
  const { data, error, isLoading, mutate } = useSWR<SystemUsageResponse>(
    url,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );

  return { usage: data, isLoading, error, refetch: mutate };
}
