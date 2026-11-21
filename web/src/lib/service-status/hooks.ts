import useSWR from "swr";
import { errorHandlingFetcher, skipRetryOnAuthError } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { ClusterStatus, SearchActivity } from "@/lib/service-status/types";

// The backend shares one cluster read for 60 seconds.
const REFRESH_INTERVAL_MS = 60_000;

export function useClusterStatus() {
  return useSWR<ClusterStatus>(
    SWR_KEYS.serviceStatusOpenSearch,
    errorHandlingFetcher,
    {
      onErrorRetry: skipRetryOnAuthError,
      refreshInterval: REFRESH_INTERVAL_MS,
      revalidateOnFocus: false,
    }
  );
}

export function useSearchActivity() {
  return useSWR<SearchActivity>(
    SWR_KEYS.serviceStatusSearches,
    errorHandlingFetcher,
    {
      onErrorRetry: skipRetryOnAuthError,
      refreshInterval: REFRESH_INTERVAL_MS,
      revalidateOnFocus: false,
    }
  );
}

/** Reads the cluster again, skipping the backend's shared result. */
export async function refreshClusterStatus(): Promise<ClusterStatus> {
  return errorHandlingFetcher<ClusterStatus>(
    `${SWR_KEYS.serviceStatusOpenSearch}?refresh=true`
  );
}
