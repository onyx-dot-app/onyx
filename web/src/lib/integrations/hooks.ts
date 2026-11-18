"use client";

import useSWR from "swr";
import { errorHandlingFetcher, skipRetryOnAuthError } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  AdminIntegration,
  AdminIntegrationDetail,
  AgentPluginOption,
  IntegrationActionsResponse,
  IntegrationPreset,
  MemberActionPolicies,
  MemberIntegration,
} from "@/lib/integrations/types";

export function useAdminIntegrations() {
  return useSWR<AdminIntegration[], Error>(
    SWR_KEYS.adminIntegrations,
    errorHandlingFetcher,
    { onErrorRetry: skipRetryOnAuthError }
  );
}

/** Plugins with integrations that the user can attach to an agent. */
export function useAgentPluginCatalog() {
  return useSWR<AgentPluginOption[], Error>(
    SWR_KEYS.agentPluginCatalog,
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

export function useMemberIntegrations() {
  return useSWR<MemberIntegration[], Error>(
    SWR_KEYS.integrations,
    errorHandlingFetcher,
    { onErrorRetry: skipRetryOnAuthError }
  );
}

/** The user's "Always allow" choices. Pass `null` to skip the request. */
export function useMemberActionPolicies(id: number | null) {
  return useSWR<MemberActionPolicies, Error>(
    id === null ? null : SWR_KEYS.integrationActionPolicies(id),
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
