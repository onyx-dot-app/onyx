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

export function useAdminIntegrationActions(id: number) {
  return useSWR<IntegrationActionsResponse, Error>(
    SWR_KEYS.adminIntegrationActions(id),
    errorHandlingFetcher,
    { onErrorRetry: skipRetryOnAuthError }
  );
}

export function useIntegrationPresets(enabled: boolean) {
  return useSWR<IntegrationPreset[], Error>(
    enabled ? SWR_KEYS.adminIntegrationPresets : null,
    errorHandlingFetcher,
    { onErrorRetry: skipRetryOnAuthError }
  );
}
