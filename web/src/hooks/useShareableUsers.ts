"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
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
    enabled ? SWR_KEYS.shareableUsers(includeApiKeys) : null,
    errorHandlingFetcher
  );

  return {
    data,
    isLoading,
    error,
    refreshShareableUsers: mutate,
  };
}
