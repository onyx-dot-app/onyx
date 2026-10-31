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
