import useSWR from "swr";

import { errorHandlingFetcher } from "@/lib/fetcher";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
import type { ScimTokenResponse } from "@/app/admin/scim/interfaces";
import { SWR_KEYS } from "@/lib/swr-keys";

export function useScimToken() {
  // The endpoint is Enterprise-gated server-side; probing below that tier
  // is a guaranteed 402, so skip the fetch entirely.
  const enterpriseTier = useTierAtLeast(Tier.ENTERPRISE);

  const { data, error, isLoading, mutate } = useSWR<ScimTokenResponse | null>(
    enterpriseTier ? SWR_KEYS.scimToken : null,
    errorHandlingFetcher,
    { shouldRetryOnError: false }
  );

  return { data, error, isLoading, mutate };
}
