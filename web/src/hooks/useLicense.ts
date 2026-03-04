import useSWR from "swr";

import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { LicenseStatus } from "@/lib/billing/interfaces";
import { useSettingsContext } from "@/providers/SettingsProvider";

const EMPTY_STATE = {
  data: undefined,
  isLoading: false,
  error: undefined,
  refresh: () => Promise.resolve(undefined),
};

/**
 * Hook to fetch license status for self-hosted deployments.
 *
 * Skips the fetch when:
 * - Cloud deployment (uses tenant auth instead)
 * - Backend is not running EE (CE has no /license route)
 *
 * Uses `running_ee_backend` from settings to determine if the /license
 * endpoint exists. This prevents 404s on CE deployments.
 */
export function useLicense() {
  const { settings } = useSettingsContext();

  // running_ee_backend tells us if EE API routes are registered.
  // Only fetch when: not cloud AND backend has the /license endpoint.
  const url =
    NEXT_PUBLIC_CLOUD_ENABLED || !settings.running_ee_backend
      ? null
      : "/api/license";

  const { data, error, mutate, isLoading } = useSWR<LicenseStatus>(
    url,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      dedupingInterval: 30000,
      shouldRetryOnError: false,
      keepPreviousData: true,
    }
  );

  return url ? { data, isLoading, error, refresh: mutate } : EMPTY_STATE;
}
