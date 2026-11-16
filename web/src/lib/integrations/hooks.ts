"use client";

import useSWR from "swr";
import { errorHandlingFetcher, skipRetryOnAuthError } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  AdminIntegration,
  AdminIntegrationDetail,
  IntegrationActionsResponse,
  IntegrationPreset,
} from "@/lib/integrations/types";

/** Every integration the admin can see, with its plugins and status. */
export function useAdminIntegrations() {
  return useSWR<AdminIntegration[], Error>(
    SWR_KEYS.adminIntegrations,
    errorHandlingFetcher,
    { onErrorRetry: skipRetryOnAuthError }
  );
}

export function useAdminIntegration(id: number) {
  return useSWR<AdminIntegrationDetail, Error>(
    SWR_KEYS.adminIntegration(id),
    errorHandlingFetcher,
    { onErrorRetry: skipRetryOnAuthError }
  );
}

/** Actions of one integration. Pass `null` to wait, e.g. until it loads. */
export function useAdminIntegrationActions(id: number | null) {
  return useSWR<IntegrationActionsResponse, Error>(
    id === null ? null : SWR_KEYS.adminIntegrationActions(id),
    errorHandlingFetcher,
    { onErrorRetry: skipRetryOnAuthError }
  );
}

/** Built-in app presets. Pass `false` to skip the request. */
export function useIntegrationPresets(enabled: boolean) {
  return useSWR<IntegrationPreset[], Error>(
    enabled ? SWR_KEYS.adminIntegrationPresets : null,
    errorHandlingFetcher,
    { onErrorRetry: skipRetryOnAuthError }
  );
}
