import useSWR, { type SWRResponse } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher, isAuthStatusError } from "@/lib/fetcher";
import { ResourceHealth } from "@/lib/opensearch-health/types";
import { useUser } from "@/providers/UserProvider";

const HEALTH_REFRESH_INTERVAL_MS: number = 5 * 60 * 1000;

export function useOpenSearchResourceHealth(): SWRResponse<
  ResourceHealth,
  Error
> {
  const { user, isAdmin } = useUser();
  return useSWR<ResourceHealth, Error>(
    isAdmin && user ? [SWR_KEYS.opensearchResourceHealth, user.id] : null,
    ([url]: [string, string]) => errorHandlingFetcher<ResourceHealth>(url),
    {
      refreshInterval: HEALTH_REFRESH_INTERVAL_MS,
      dedupingInterval: 60 * 1000,
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      onErrorRetry: (error, _key, _config, revalidate, { retryCount }) => {
        if (isAuthStatusError(error)) return;
        // SWR pauses interval refresh after errors; resume at the same quiet cadence.
        setTimeout(
          () => revalidate({ retryCount }),
          HEALTH_REFRESH_INTERVAL_MS
        );
      },
    }
  );
}
