/**
 * Billing UI Constants
 *
 * Centralized configuration for pricing, URLs, thresholds, and defaults.
 * Update these values when pricing changes or external URLs move.
 */

// ----------------------------------------------------------------------------
// Pricing
// ----------------------------------------------------------------------------

/** Monthly price per seat in USD */
export const MONTHLY_PRICE_PER_SEAT = 25;

/** Annual price per seat/month in USD (billed annually) */
export const ANNUAL_PRICE_PER_SEAT = 20;

/** Annual billing discount percentage */
export const ANNUAL_DISCOUNT_PERCENT = Math.round(
  ((MONTHLY_PRICE_PER_SEAT - ANNUAL_PRICE_PER_SEAT) / MONTHLY_PRICE_PER_SEAT) *
    100
);

/** Minimum number of seats allowed */
export const MIN_SEAT_COUNT = 1;

/** Free trial duration in months */
export const FREE_TRIAL_MONTHS = 1;

// ----------------------------------------------------------------------------
// Grace Period & Expiration Thresholds
// ----------------------------------------------------------------------------

/** Days after expiration before data deletion */
export const GRACE_PERIOD_DAYS = 30;

/** Days before expiration to show error banner (subscription expired) */
export const EXPIRATION_ERROR_THRESHOLD_DAYS = 0;

/** Days before expiration to show warning banner */
export const EXPIRATION_WARNING_THRESHOLD_DAYS = 14;

/** Days before expiration to show info banner */
export const EXPIRATION_INFO_THRESHOLD_DAYS = 30;

// ----------------------------------------------------------------------------
// External URLs
// ----------------------------------------------------------------------------

/** Contact sales page URL */
export const SALES_URL = "https://www.onyx.app/contact-sales";

/** Support email address */
export const SUPPORT_EMAIL = "support@onyx.app";

// ----------------------------------------------------------------------------
// Plan Names
// ----------------------------------------------------------------------------

export const PLAN_NAMES = {
  BUSINESS: "Business",
  ENTERPRISE: "Enterprise",
} as const;
