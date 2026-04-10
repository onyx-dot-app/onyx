"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { Ruleset } from "@/app/proposal-review/types";

export function useRulesets() {
  const { data, error, isLoading } = useSWR<Ruleset[]>(
    "/api/proposal-review/rulesets",
    errorHandlingFetcher
  );

  const rulesets = data ?? [];
  const defaultRuleset = rulesets.find((r) => r.is_default) ?? rulesets[0];

  return {
    rulesets,
    defaultRuleset: defaultRuleset ?? null,
    error,
    isLoading,
  };
}
