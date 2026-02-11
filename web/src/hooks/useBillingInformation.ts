import useSWR from "swr";

import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  BillingInformation,
  SubscriptionStatus,
} from "@/lib/billing/interfaces";

/**
 * Hook to fetch billing information from Stripe.
 *
 * Works for both cloud and self-hosted deployments:
 * - Cloud: fetches from /api/tenants/billing-information (legacy endpoint)
 * - Self-hosted: fetches from /api/admin/billing/billing-information
 *
 * Returns subscription status, seats, billing period, etc.
 *
 * @example
 * ```tsx
 * const { data, isLoading, error, refresh } = useBillingInformation();
 *
 * if (isLoading) return <Loading />;
 * if (error) return <Error />;
 * if (!data || !hasActiveSubscription(data)) return <NoSubscription />;
 *
 * return <BillingDetails billing={data} />;
 * ```
 */
export function useBillingInformation() {
  const url = NEXT_PUBLIC_CLOUD_ENABLED
    ? "/api/tenants/billing-information"
    : "/api/admin/billing/billing-information";

  const { data, error, mutate, isLoading } = useSWR<
    BillingInformation | SubscriptionStatus
  >(url, errorHandlingFetcher, {
    revalidateOnFocus: false,
    revalidateOnReconnect: false,
    dedupingInterval: 30000,
    // Don't auto-retry on errors (circuit breaker will block requests anyway)
    shouldRetryOnError: false,
    // Keep previous data while revalidating to prevent UI flashing
    keepPreviousData: true,
  });

  return {
    data,
    isLoading,
    error,
    refresh: mutate,
  };
}
