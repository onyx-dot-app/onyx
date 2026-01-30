/**
 * Backwards-compatible exports from billing module.
 *
 * New code should import directly from:
 * - @/lib/billing/interfaces (types)
 * - @/lib/billing/svc (mutations)
 * - @/hooks/useBillingInformation (hook)
 * - @/hooks/useLicense (hook)
 */

import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";

// Re-export hook
export { useBillingInformation } from "@/hooks/useBillingInformation";

// Re-export utilities and types
export { statusToDisplay, hasActiveSubscription } from "./interfaces";
export type { BillingInformation } from "./interfaces";

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
