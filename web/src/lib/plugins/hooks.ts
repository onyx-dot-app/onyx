"use client";

import { useCallback, useMemo } from "react";
import useSWR from "swr";
import { errorHandlingFetcher, skipRetryOnAuthError } from "@/lib/fetcher";
import { useMemberIntegrations } from "@/lib/integrations/hooks";
import type { MemberIntegration } from "@/lib/integrations/types";
import { SWR_KEYS } from "@/lib/swr-keys";

/** One plugin of an agent that holds integrations the user can use. */
export interface ChatPluginEntry {
  pluginId: string;
  name: string;
  integrations: MemberIntegration[];
}

export interface AgentChatPlugins {
  /** Every plugin of the agent, null until it loads. Tool options name these. */
  pluginIds: string[] | null;
  /** The agent's plugins that hold integrations, sorted by name. */
  plugins: ChatPluginEntry[];
  isLoading: boolean;
  error: Error | undefined;
  /** Reads the integration statuses again. */
  refresh: () => Promise<void>;
}

/**
 * The plugins a chat of the agent runs for the user, as the server decides
 * them. Null until it loads and on a failed read: an empty list would read
 * as a complete catalog, and the composer would leave every plugin out of a
 * send.
 */
export function useAgentPluginIds(agentId: number | undefined) {
  const { data, error, isLoading } = useSWR<string[], Error>(
    agentId === undefined ? null : SWR_KEYS.agentPluginIds(agentId),
    errorHandlingFetcher,
    { onErrorRetry: skipRetryOnAuthError, revalidateOnFocus: false }
  );
  const pluginIds = useMemo(
    () => (data === undefined ? null : [...new Set(data)].sort()),
    [data]
  );
  return { pluginIds, error, isLoading };
}

/** The plugins of an agent with the integrations they hold. */
export function useAgentChatPlugins(
  agentId: number | undefined
): AgentChatPlugins {
  const integrations = useMemberIntegrations();
  const ids = useAgentPluginIds(agentId);
  const data = integrations.data;
  const { pluginIds } = ids;

  const plugins = useMemo(() => {
    const byPlugin = new Map<string, ChatPluginEntry>();
    for (const integration of data ?? []) {
      for (const ref of integration.plugins) {
        const entry = byPlugin.get(ref.plugin_id);
        if (entry) entry.integrations.push(integration);
        else
          byPlugin.set(ref.plugin_id, {
            pluginId: ref.plugin_id,
            name: ref.plugin_name,
            integrations: [integration],
          });
      }
    }
    return (pluginIds ?? [])
      .flatMap((id) => {
        const entry = byPlugin.get(id);
        return entry ? [entry] : [];
      })
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [data, pluginIds]);

  const { mutate: refreshIntegrations } = integrations;
  const refresh = useCallback(async () => {
    await refreshIntegrations();
  }, [refreshIntegrations]);

  return {
    pluginIds,
    plugins,
    isLoading: integrations.isLoading || ids.isLoading,
    error: integrations.error ?? ids.error,
    refresh,
  };
}

interface AgentPreference {
  disabled_plugin_ids?: string[] | null;
}

type AgentPreferences = Record<string, AgentPreference>;

interface PendingWrite {
  body: AgentPreference | null;
}

// The PATCH replaces the agent's record, so writes run one at a time.
let preferenceWrites: Promise<unknown> = Promise.resolve();

/** The plugins the user turned off for each agent (`disabled_plugin_ids`). */
export function useAgentPluginPreferences(enabled: boolean) {
  const { data, error, mutate } = useSWR<AgentPreferences | null, Error>(
    enabled ? SWR_KEYS.assistantPreferences : null,
    errorHandlingFetcher,
    { onErrorRetry: skipRetryOnAuthError, revalidateOnFocus: false }
  );
  // A failed read is not loaded: an empty list would show every plugin on,
  // and a switch could not save.
  const loaded = !enabled || data !== undefined;

  const disabledPluginIds = useCallback(
    (agentId: number): string[] | null =>
      loaded ? (data?.[String(agentId)]?.disabled_plugin_ids ?? []) : null,
    [data, loaded]
  );
  const retry = useCallback(() => mutate(), [mutate]);

  const setPluginsDisabled = useCallback(
    async (
      agentId: number,
      pluginIds: readonly string[],
      disabled: boolean
    ): Promise<void> => {
      const key = String(agentId);
      const pending: PendingWrite = { body: null };
      await mutate(
        (current) => {
          // Not loaded: a write would drop the saved plugin choices.
          if (current === undefined) return current;
          const record = current?.[key];
          const saved = record?.disabled_plugin_ids ?? [];
          const next = disabled
            ? [...new Set([...saved, ...pluginIds])]
            : saved.filter((id) => !pluginIds.includes(id));
          pending.body = { disabled_plugin_ids: next };
          return {
            ...current,
            [key]: { ...record, disabled_plugin_ids: next },
          };
        },
        { revalidate: false }
      );
      const sent = pending.body;
      if (sent === null)
        throw new Error("The plugin preferences have not loaded.");
      const write = preferenceWrites.then(async () => {
        const response = await fetch(
          `/api/user/assistant/${agentId}/preferences`,
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(sent),
          }
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
      });
      preferenceWrites = write.catch(() => undefined);
      try {
        await write;
      } catch (writeError) {
        void mutate();
        throw writeError;
      }
    },
    [mutate]
  );

  return { loaded, error, retry, disabledPluginIds, setPluginsDisabled };
}
