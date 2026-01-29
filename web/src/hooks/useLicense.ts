import useSWR from "swr";

import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { LicenseStatus } from "@/lib/billing/interfaces";

/**
 * Hook to fetch license status for self-hosted deployments.
 *
 * Returns license information including seats, expiry, and status.
 * Only fetches for self-hosted deployments (cloud uses tenant auth instead).
 *
 * @example
 * ```tsx
 * const { data, isLoading, error, refresh } = useLicense();
 *
 * if (isLoading) return <Loading />;
 * if (error) return <Error />;
 * if (!data?.has_license) return <NoLicense />;
 *
 * return <LicenseDetails license={data} />;
 * ```
 */
export function useLicense() {
  // Only fetch license for self-hosted deployments
  // Cloud deployments use tenant-based auth, not license files
  const url = NEXT_PUBLIC_CLOUD_ENABLED ? null : "/api/license";

  const { data, error, mutate, isLoading } = useSWR<LicenseStatus>(
    url,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 30000,
    }
  );

  // Return empty state for cloud deployments
  if (NEXT_PUBLIC_CLOUD_ENABLED) {
    return {
      data: null,
      isLoading: false,
      error: undefined,
      refresh: () => Promise.resolve(undefined),
    };
  }

  return {
    data,
    isLoading,
    error,
    refresh: mutate,
  };
}
