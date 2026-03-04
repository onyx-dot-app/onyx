import useSWR from "swr";

import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  BillingInformation,
  SubscriptionStatus,
} from "@/lib/billing/interfaces";
import { useSettingsContext } from "@/providers/SettingsProvider";

const EMPTY_STATE = {
  data: undefined,
  isLoading: false,
  error: undefined,
  refresh: () => Promise.resolve(undefined),
};

/**
 * Hook to fetch billing information from Stripe.
 *
 * Works for both cloud and self-hosted deployments:
 * - Cloud: always fetches from /api/tenants/billing-information
 * - Self-hosted EE: fetches from /api/admin/billing/billing-information
 * - Self-hosted CE: skips fetch entirely (route doesn't exist)
 *
 * Uses `running_ee_backend` from settings to determine if the billing
 * endpoint exists. This prevents 404s on CE deployments.
 */
export function useBillingInformation() {
  const { settings } = useSettingsContext();

  // running_ee_backend tells us if EE API routes are registered.
  // Cloud always has billing; self-hosted only when backend is EE.
  const url = NEXT_PUBLIC_CLOUD_ENABLED
    ? "/api/tenants/billing-information"
    : settings.running_ee_backend
      ? "/api/admin/billing/billing-information"
      : null;

  const { data, error, mutate, isLoading } = useSWR<
    BillingInformation | SubscriptionStatus
  >(url, errorHandlingFetcher, {
    revalidateOnFocus: false,
    revalidateOnReconnect: false,
    dedupingInterval: 30000,
    shouldRetryOnError: false,
    keepPreviousData: true,
  });

  if (!url) {
    return EMPTY_STATE;
  }

  return {
    data,
    isLoading,
    error,
    refresh: mutate,
  };
}
