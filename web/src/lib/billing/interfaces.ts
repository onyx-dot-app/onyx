/**
 * Billing and License interfaces.
 *
 * These types match the backend Pydantic models:
 * - LicenseStatusResponse (backend/ee/onyx/server/license/models.py)
 * - BillingInformationResponse (backend/ee/onyx/server/billing/models.py)
 */

// ----------------------------------------------------------------------------
// License Types (Self-hosted only)
// ----------------------------------------------------------------------------

export type PlanType = "monthly" | "annual";

export type LicenseSource = "auto_fetch" | "manual_upload";

export type ApplicationStatus =
  | "active"
  | "payment_reminder"
  | "gated_access"
  | "expired"
  | "seat_limit_exceeded";

/**
 * Billing status from Stripe subscription.
 */
export enum BillingStatus {
  TRIALING = "trialing",
  ACTIVE = "active",
  CANCELLED = "cancelled",
  EXPIRED = "expired",
  PAST_DUE = "past_due",
  UNPAID = "unpaid",
}

/**
 * License status response from /api/license endpoint.
 * Only relevant for self-hosted deployments.
 */
export interface LicenseStatus {
  has_license: boolean;
  seats: number;
  used_seats: number;
  plan_type: PlanType | null;
  issued_at: string | null;
  expires_at: string | null;
  grace_period_end: string | null;
  status: ApplicationStatus | null;
  source: LicenseSource | null;
}

// ----------------------------------------------------------------------------
// Billing Types (Cloud and Self-hosted)
// ----------------------------------------------------------------------------

/**
 * Billing information from Stripe subscription.
 * Available for both cloud and self-hosted with active subscription.
 */
export interface BillingInformation {
  tenant_id: string;
  status: string | null;
  plan_type: string | null;
  seats: number | null;
  billing_period: string | null;
  current_period_start: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  canceled_at: string | null;
  trial_start: string | null;
  trial_end: string | null;
  payment_method_enabled: boolean;
}

/**
 * Response when no subscription exists.
 */
export interface SubscriptionStatus {
  subscribed: boolean;
}

// ----------------------------------------------------------------------------
// Checkout & Portal Types
// ----------------------------------------------------------------------------

export interface CreateCheckoutSessionRequest {
  billing_period?: "monthly" | "annual";
  seats?: number;
  email?: string;
}

export interface CreateCheckoutSessionResponse {
  stripe_checkout_url: string;
}

export interface CreateCustomerPortalSessionRequest {
  return_url?: string;
}

export interface CreateCustomerPortalSessionResponse {
  stripe_customer_portal_url: string;
}

// ----------------------------------------------------------------------------
// Seat Management Types
// ----------------------------------------------------------------------------

export interface SeatUpdateRequest {
  new_seat_count: number;
}

export interface SeatUpdateResponse {
  success: boolean;
  current_seats: number;
  used_seats: number;
  message: string | null;
}

// ----------------------------------------------------------------------------
// Type Guards
// ----------------------------------------------------------------------------

/**
 * Check if the response indicates an active subscription.
 * Returns true only if the data is BillingInformation with a non-null status.
 */
export function hasActiveSubscription(
  data: BillingInformation | SubscriptionStatus
): data is BillingInformation {
  // SubscriptionStatus (bare { subscribed: boolean }) is never BillingInformation
  if ("subscribed" in data) {
    return false;
  }
  return data.status !== null;
}

/**
 * Check if the response indicates an active *paid* subscription.
 * Returns true only for status === "active" (excludes trialing, past_due, etc.).
 */
export function hasPaidSubscription(
  data: BillingInformation | SubscriptionStatus
): data is BillingInformation {
  if ("subscribed" in data) {
    return false;
  }
  return data.status === BillingStatus.ACTIVE;
}

/**
 * Check if a license is valid and active.
 */
export function isLicenseValid(license: LicenseStatus): boolean {
  return license.has_license && license.status === "active";
}

// ----------------------------------------------------------------------------
// Display Utilities
// ----------------------------------------------------------------------------

/**
 * Convert status string to human-readable display format.
 */
export function statusToDisplay(status: string | null): string {
  if (!status) return "Unknown";

  switch (status) {
    case "trialing":
      return "Trialing";
    case "active":
      return "Active";
    case "canceled":
    case "cancelled":
      return "Canceled";
    case "past_due":
      return "Past Due";
    case "unpaid":
      return "Unpaid";
    case "expired":
      return "Expired";
    default:
      return status.charAt(0).toUpperCase() + status.slice(1);
  }
}
