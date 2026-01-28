/**
 * Backwards-compatible exports from billing module.
 *
 * New code should import directly from:
 * - @/lib/billing/interfaces (types)
 * - @/lib/billing/actions (mutations)
 * - @/lib/hooks/useBillingInformation (hook)
 * - @/lib/hooks/useLicense (hook)
 */

import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";

// Re-export hook
export { useBillingInformation } from "@/lib/hooks/useBillingInformation";

// Re-export utilities
export { statusToDisplay, hasActiveSubscription } from "./interfaces";

// Legacy function - returns raw Response for backwards compatibility
export async function fetchCustomerPortal(): Promise<Response> {
  const url = NEXT_PUBLIC_CLOUD_ENABLED
    ? "/api/tenants/create-customer-portal-session"
    : "/api/admin/billing/create-customer-portal-session";

  return fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  });
}
