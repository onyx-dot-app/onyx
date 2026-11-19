"use client";

import { useCallback, useMemo } from "react";
import useSWR from "swr";
import { errorHandlingFetcher, skipRetryOnAuthError } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  AdminIntegration,
  AdminIntegrationDetail,
  AgentCatalogIntegration,
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

/** The integrations that the user can attach to an agent. */
export function useAgentIntegrationCatalog() {
  return useSWR<AgentCatalogIntegration[], Error>(
    SWR_KEYS.agentIntegrationCatalog,
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

export interface AgentChatIntegrations {
  /** Every integration of the agent, null until it loads. Tool options name
   * these. */
  integrationIds: number[] | null;
  /** The agent's integrations that the user can read, sorted by name. */
  integrations: MemberIntegration[];
  isLoading: boolean;
  error: Error | undefined;
  /** Reads the integration statuses and the agent's integrations again. */
  refresh: () => Promise<void>;
}

/**
 * The integrations a chat of the agent uses for the user, as the server
 * decides them. Null until it loads and on a failed read: an empty list would
 * read as a complete catalog, and the composer would leave every integration
 * out of a send.
 */
export function useAgentIntegrationIds(agentId: number | undefined) {
  // Revalidates on focus: turning an integration on in another tab changes
  // which ids the default agent uses.
  const { data, error, isLoading, mutate } = useSWR<number[], Error>(
    agentId === undefined ? null : SWR_KEYS.agentIntegrationIds(agentId),
    errorHandlingFetcher,
    { onErrorRetry: skipRetryOnAuthError }
  );
  // SWR keeps the last data after a failed read, so an error means unknown.
  const integrationIds = useMemo(
    () =>
      data === undefined || error !== undefined
        ? null
        : [...new Set(data)].sort((a, b) => a - b),
    [data, error]
  );
  return { integrationIds, error, isLoading, mutate };
}

/** The integrations of an agent that a chat uses for the user. */
export function useAgentChatIntegrations(
  agentId: number | undefined
): AgentChatIntegrations {
  const members = useMemberIntegrations();
  const ids = useAgentIntegrationIds(agentId);
  const data = members.data;
  const { integrationIds } = ids;

  const integrations = useMemo(() => {
    const wanted = new Set(integrationIds ?? []);
    return (data ?? [])
      .filter((integration) => wanted.has(integration.id))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [data, integrationIds]);

  const { mutate: refreshIntegrations } = members;
  const { mutate: refreshIds } = ids;
  const refresh = useCallback(async () => {
    await Promise.all([refreshIntegrations(), refreshIds()]);
  }, [refreshIntegrations, refreshIds]);

  return {
    integrationIds,
    integrations,
    isLoading: members.isLoading || ids.isLoading,
    error: members.error ?? ids.error,
    refresh,
  };
}

interface AgentPreference {
  disabled_integration_ids?: number[] | null;
}

type AgentPreferences = Record<string, AgentPreference>;

interface PendingWrite {
  body: AgentPreference | null;
}

// The PATCH replaces the agent's record, so writes run one at a time.
let preferenceWrites: Promise<unknown> = Promise.resolve();

/** The integrations the user turned off for each agent
 * (`disabled_integration_ids`). */
export function useAgentIntegrationPreferences(enabled: boolean) {
  const { data, error, mutate } = useSWR<AgentPreferences | null, Error>(
    enabled ? SWR_KEYS.assistantPreferences : null,
    errorHandlingFetcher,
    { onErrorRetry: skipRetryOnAuthError, revalidateOnFocus: false }
  );
  // A failed read is not loaded: an empty list would show each integration on,
  // and a switch could not save.
  const loaded = !enabled || data !== undefined;

  const disabledIntegrationIds = useCallback(
    (agentId: number): number[] | null =>
      loaded ? (data?.[String(agentId)]?.disabled_integration_ids ?? []) : null,
    [data, loaded]
  );
  const retry = useCallback(() => mutate(), [mutate]);

  const setIntegrationsDisabled = useCallback(
    async (
      agentId: number,
      integrationIds: readonly number[],
      disabled: boolean
    ): Promise<void> => {
      const key = String(agentId);
      // The whole read, change, write and recovery runs in the queue, so a
      // failed write is read back before the next body is built.
      const run = async (): Promise<void> => {
        const pending: PendingWrite = { body: null };
        await mutate(
          (current) => {
            // Not loaded: a write would drop the saved choices.
            if (current === undefined) return current;
            const record = current?.[key];
            const saved = record?.disabled_integration_ids ?? [];
            const next = disabled
              ? [...new Set([...saved, ...integrationIds])]
              : saved.filter((id) => !integrationIds.includes(id));
            pending.body = { disabled_integration_ids: next };
            return {
              ...current,
              [key]: { ...record, disabled_integration_ids: next },
            };
          },
          { revalidate: false }
        );
        const sent = pending.body;
        if (sent === null)
          throw new Error("The integration preferences have not loaded.");
        try {
          const response = await fetch(
            `/api/user/assistant/${agentId}/preferences`,
            {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(sent),
            }
          );
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
        } catch (writeError) {
          // A refused or lost write: read the saved list back.
          await mutate();
          throw writeError;
        }
      };
      const write = preferenceWrites.then(run);
      preferenceWrites = write.catch(() => undefined);
      await write;
    },
    [mutate]
  );

  return {
    loaded,
    error,
    retry,
    disabledIntegrationIds,
    setIntegrationsDisabled,
  };
}
