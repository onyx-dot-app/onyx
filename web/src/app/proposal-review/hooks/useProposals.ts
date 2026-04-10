"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { Proposal } from "@/app/proposal-review/types";

const PROPOSALS_URL = "/api/proposal-review/proposals";

interface ProposalListResponse {
  proposals: Proposal[];
  total_count: number;
  config_missing: boolean;
}

export function useProposals() {
  const { data, error, isLoading, mutate } = useSWR<ProposalListResponse>(
    PROPOSALS_URL,
    errorHandlingFetcher
  );

  return {
    proposals: data?.proposals ?? [],
    totalCount: data?.total_count ?? 0,
    configMissing: data?.config_missing ?? false,
    error,
    isLoading,
    mutate,
  };
}
