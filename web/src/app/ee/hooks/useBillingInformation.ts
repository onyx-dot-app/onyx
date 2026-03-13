import useSWR from "swr";

import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  BillingInformation,
  SubscriptionStatus,
} from "@/lib/ee/billing/interfaces";

/**
 * Hook to fetch billing information from Stripe.
 *
 * Works for both cloud and self-hosted deployments:
 * - Cloud: fetches from /api/tenants/billing-information
 * - Self-hosted: fetches from /api/admin/billing/billing-information
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
    shouldRetryOnError: false,
    keepPreviousData: true,
  });

  return { data, isLoading, error, refresh: mutate };
}
