"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { MinimalUserSnapshot } from "@/lib/types";

export interface UseShareableUsersParams {
  includeApiKeys: boolean;
}

export default function useShareableUsers({
  includeApiKeys,
}: UseShareableUsersParams) {
  const { data, error, mutate, isLoading } = useSWR<MinimalUserSnapshot[]>(
    `/api/users?include_api_keys=${includeApiKeys}`,
    errorHandlingFetcher
  );

  return {
    data,
    isLoading,
    error,
    refreshShareableUsers: mutate,
  };
}
