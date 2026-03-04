import useSWR from "swr";

import { errorHandlingFetcher } from "@/lib/fetcher";
import type { ScimTokenResponse } from "@/app/admin/scim/interfaces";

const TOKEN_URL = "/api/admin/enterprise-settings/scim/token";

export function useScimToken() {
  const { data, error, isLoading, mutate } = useSWR<ScimTokenResponse>(
    TOKEN_URL,
    errorHandlingFetcher,
    { shouldRetryOnError: false }
  );

  return { data, error, isLoading, mutate };
}
