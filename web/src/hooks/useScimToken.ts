import useSWR from "swr";

import { errorHandlingFetcher } from "@/lib/fetcher";
import type { ScimTokenResponse } from "@/app/admin/scim/interfaces";
import { SWR_KEYS } from "@/lib/swr-keys";

export function useScimToken() {
  const { data, error, isLoading, mutate } = useSWR<ScimTokenResponse>(
    SWR_KEYS.scimToken,
    errorHandlingFetcher,
    { shouldRetryOnError: false }
  );

  return { data, error, isLoading, mutate };
}
