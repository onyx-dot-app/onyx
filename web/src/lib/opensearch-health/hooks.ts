import useSWR from "swr";
import { errorHandlingFetcher, isAuthStatusError } from "@/lib/fetcher";
import { ResourceHealth } from "@/lib/opensearch-health/types";
import { useUser } from "@/providers/UserProvider";

export const RESOURCE_HEALTH_URL = "/api/manage/admin/opensearch-health";
const HEALTH_REFRESH_INTERVAL_MS = 5 * 60 * 1000;

export function useOpenSearchResourceHealth() {
  const { user, isAdmin } = useUser();
  return useSWR<ResourceHealth>(
    isAdmin && user ? [RESOURCE_HEALTH_URL, user.id] : null,
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
