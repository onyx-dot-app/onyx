/**
 * Billing action functions for mutations.
 *
 * These are async functions for one-off actions like creating
 * checkout sessions or portal sessions. They don't need SWR caching.
 *
 * Endpoints:
 * - Cloud: /api/tenants/* (legacy, will migrate to /api/admin/billing/*)
 * - Self-hosted: /api/admin/billing/* (unified billing API)
 *
 * License actions (self-hosted only):
 * - /api/license/fetch - Fetch license from control plane after checkout
 * - /api/license/refresh - Refresh cached license data
 * - /api/license/upload - Upload license key manually (air-gapped deployments)
 */

import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import {
  CreateCheckoutSessionRequest,
  CreateCheckoutSessionResponse,
  CreateCustomerPortalSessionRequest,
  CreateCustomerPortalSessionResponse,
  SeatUpdateRequest,
  SeatUpdateResponse,
} from "@/lib/billing/interfaces";

function getBillingBaseUrl(): string {
  return NEXT_PUBLIC_CLOUD_ENABLED ? "/api/tenants" : "/api/admin/billing";
}

async function billingPost<T>(endpoint: string, body?: unknown): Promise<T> {
  const response = await fetch(`${getBillingBaseUrl()}${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || "Billing request failed");
  }

  return response.json();
}

export const createCheckoutSession = (request?: CreateCheckoutSessionRequest) =>
  billingPost<CreateCheckoutSessionResponse>(
    "/create-checkout-session",
    request
  );

export const createCustomerPortalSession = (
  request?: CreateCustomerPortalSessionRequest
) =>
  billingPost<CreateCustomerPortalSessionResponse>(
    "/create-customer-portal-session",
    request
  );

export const updateSeatCount = (request: SeatUpdateRequest) =>
  billingPost<SeatUpdateResponse>("/seats/update", request);

/**
 * Reset the Stripe connection circuit breaker (self-hosted only).
 * Called when user clicks "Connect to Stripe" to retry after a previous failure.
 */
export const resetStripeConnection = () =>
  billingPost<{ success: boolean; message: string }>("/reset-connection");

// Self-hosted only actions
async function selfHostedPost<T>(endpoint: string): Promise<T> {
  if (NEXT_PUBLIC_CLOUD_ENABLED) {
    throw new Error(`${endpoint} is only available for self-hosted`);
  }

  const response = await fetch(`/api/license${endpoint}`, {
    method: "POST",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || "License request failed");
  }

  return response.json();
}

/**
 * Claim a license from the control plane (self-hosted only).
 *
 * Two modes:
 * - With sessionId: After Stripe checkout, exchange session_id for license
 * - Without sessionId: Re-claim using existing license for auth
 */
export const claimLicense = (sessionId?: string) =>
  selfHostedPost<{ success: boolean; license?: unknown }>(
    sessionId ? `/claim?session_id=${encodeURIComponent(sessionId)}` : "/claim"
  );

/**
 * Refresh the cached license data (self-hosted only).
 * Forces a re-read of the license and updates the cache.
 */
export const refreshLicenseCache = () =>
  selfHostedPost<{ success: boolean; message?: string }>("/refresh");

/**
 * Upload a license key string (self-hosted only).
 * Used for air-gapped deployments where users paste license keys manually.
 */
export async function uploadLicense(
  licenseKey: string
): Promise<{ success: boolean; message?: string }> {
  if (NEXT_PUBLIC_CLOUD_ENABLED) {
    throw new Error("License upload is only available for self-hosted");
  }

  // Create a file from the license key string
  const blob = new Blob([licenseKey], { type: "text/plain" });
  const formData = new FormData();
  formData.append("license_file", blob, "license.txt");

  const response = await fetch("/api/license/upload", {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || "License upload failed");
  }

  return response.json();
}
