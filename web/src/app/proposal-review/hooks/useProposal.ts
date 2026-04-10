"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { Proposal } from "@/app/proposal-review/types";

export function useProposal(proposalId: string | null) {
  const { data, error, isLoading, mutate } = useSWR<Proposal>(
    proposalId ? `/api/proposal-review/proposals/${proposalId}` : null,
    errorHandlingFetcher
  );

  return {
    proposal: data ?? null,
    error,
    isLoading,
    mutate,
  };
}
