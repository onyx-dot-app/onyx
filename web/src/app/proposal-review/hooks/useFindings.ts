"use client";

import { useMemo } from "react";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { Finding, FindingsByCategory } from "@/app/proposal-review/types";

const NATURAL_SORT_OPTIONS = { numeric: true, sensitivity: "base" } as const;

export function useFindings(proposalId: string | null) {
  const { data, error, isLoading, mutate } = useSWR<Finding[]>(
    proposalId ? `/api/proposal-review/proposals/${proposalId}/findings` : null,
    errorHandlingFetcher
  );

  const findings = data ?? [];

  const findingsByCategory = useMemo(() => {
    const result: FindingsByCategory[] = [];
    const categoryMap = new Map<string, Finding[]>();

    for (const finding of findings) {
      const cat = finding.rule_category ?? "Uncategorized";
      const existing = categoryMap.get(cat);
      if (existing) {
        existing.push(finding);
      } else {
        categoryMap.set(cat, [finding]);
      }
    }

    categoryMap.forEach((catFindings, category) => {
      result.push({ category, findings: catFindings });
    });

    // Natural sort so "IR 2" comes before "IR 10"
    result.sort((a, b) =>
      a.category.localeCompare(b.category, undefined, NATURAL_SORT_OPTIONS)
    );

    return result;
  }, [findings]);

  return {
    findings,
    findingsByCategory,
    error,
    isLoading,
    mutate,
  };
}
