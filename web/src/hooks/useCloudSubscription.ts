import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { hasPaidSubscription } from "@/lib/billing/interfaces";
import { useBillingInformation } from "@/hooks/useBillingInformation";

/**
 * Returns whether the current tenant has an active paid subscription on cloud.
 *
 * Self-hosted deployments always return true (no billing gate).
 * Cloud deployments check billing status via the billing API.
 */
export function useCloudSubscription(): boolean {
  const { data: billingData } = useBillingInformation();

  if (!NEXT_PUBLIC_CLOUD_ENABLED) {
    return true;
  }

  return billingData != null && hasPaidSubscription(billingData);
}
