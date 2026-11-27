"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { MinimalUserSnapshot } from "@/lib/types";

export interface UseShareableUsersParams {
  includeApiKeys: boolean;
  /** False skips the fetch, for a dialog that is closed. */
  enabled?: boolean;
}

export default function useShareableUsers({
  includeApiKeys,
  enabled = true,
}: UseShareableUsersParams) {
  const { data, error, mutate, isLoading } = useSWR<MinimalUserSnapshot[]>(
    enabled ? `/api/users?include_api_keys=${includeApiKeys}` : null,
    errorHandlingFetcher
  );

  return {
    data,
    isLoading,
    error,
    refreshShareableUsers: mutate,
  };
}
