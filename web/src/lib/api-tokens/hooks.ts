"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { ApiTokenPlatform, ApiTokenView } from "@/lib/api-tokens/types";

/**
 * Saved keys for one platform. Only full admins can list them; for anyone
 * else the list is empty and the field takes a typed key only.
 */
export function useApiTokens(platform: ApiTokenPlatform | undefined) {
  const { data, error, isLoading } = useSWR<ApiTokenView[]>(
    platform ? SWR_KEYS.adminApiTokens(platform) : null,
    errorHandlingFetcher,
    { shouldRetryOnError: false }
  );
  return { tokens: data ?? [], error, isLoading };
}
