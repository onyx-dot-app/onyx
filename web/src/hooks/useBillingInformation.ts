import useSWR from "swr";

import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  BillingInformation,
  SubscriptionStatus,
} from "@/lib/billing/interfaces";

/**
 * Hook to fetch billing information from Stripe.
 *
 * Works for both cloud and self-hosted deployments:
 * - Cloud: fetches from /api/tenants/billing-information
 * - Self-hosted: fetches from /api/admin/billing/billing-information
 */
export function useBillingInformation() {
  const url = NEXT_PUBLIC_CLOUD_ENABLED
    ? SWR_KEYS.billingInformationCloud
    : SWR_KEYS.billingInformationSelfHosted;

  const { data, error, mutate, isLoading } = useSWR<
    BillingInformation | SubscriptionStatus
  >(url, errorHandlingFetcher, {
    revalidateOnFocus: false,
    revalidateOnReconnect: false,
    revalidateIfStale: false,
    dedupingInterval: 30000,
    shouldRetryOnError: false,
    keepPreviousData: true,
  });

  return { data, isLoading, error, refresh: mutate };
}
