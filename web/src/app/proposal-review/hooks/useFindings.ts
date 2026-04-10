"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { Finding, FindingsByCategory } from "@/app/proposal-review/types";

export function useFindings(proposalId: string | null) {
  const { data, error, isLoading, mutate } = useSWR<Finding[]>(
    proposalId ? `/api/proposal-review/proposals/${proposalId}/findings` : null,
    errorHandlingFetcher
  );

  const findings = data ?? [];

  // Group findings by category
  const findingsByCategory: FindingsByCategory[] = [];
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
    findingsByCategory.push({
      category,
      findings: catFindings,
    });
  });

  return {
    findings,
    findingsByCategory,
    error,
    isLoading,
    mutate,
  };
}
