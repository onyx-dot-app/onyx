"use client";

import { useCallback, useMemo } from "react";
import useSWR from "swr";
import { errorHandlingFetcher, skipRetryOnAuthError } from "@/lib/fetcher";
import { useAgent } from "@/lib/agents/hooks";
import { DEFAULT_AGENT_ID } from "@/lib/constants";
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
  refresh: () => Promise<MemberIntegration[] | undefined>;
}

/**
 * The plugins of an agent (persona detail `plugins`). The default agent has
 * none of its own: it uses each plugin of the user that holds integrations
 * and that the user turned on.
 */
export function useAgentChatPlugins(
  agentId: number | undefined
): AgentChatPlugins {
  const integrations = useMemberIntegrations();
  const isDefault = agentId === DEFAULT_AGENT_ID;
  const agent = useAgent(agentId === undefined || isDefault ? null : agentId);
  const data = integrations.data;

  const { pluginIds, plugins } = useMemo(() => {
    const byPlugin = new Map<string, ChatPluginEntry>();
    for (const integration of data ?? []) {
      for (const ref of integration.plugins) {
        if (ref.installation_policy === "NOT_AVAILABLE") continue;
        // The default agent runs only the plugins the user turned on.
        if (isDefault && !ref.enabled) continue;
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
    function agentPluginIds(): string[] | null {
      if (agentId === undefined) return null;
      if (isDefault)
        return data === undefined && !integrations.error
          ? null
          : [...byPlugin.keys()];
      if (agent.agent === null) return agent.error ? [] : null;
      return (agent.agent.plugins ?? []).map((link) => link.plugin_id);
    }
    const ids = agentPluginIds();
    const entries = (ids ?? []).flatMap((id) => {
      const entry = byPlugin.get(id);
      return entry ? [entry] : [];
    });
    return {
      pluginIds: ids === null ? null : [...new Set(ids)].sort(),
      plugins: entries.sort((a, b) => a.name.localeCompare(b.name)),
    };
  }, [agentId, isDefault, data, integrations.error, agent.agent, agent.error]);

  return {
    pluginIds,
    plugins,
    isLoading: integrations.isLoading || agent.isLoading,
    error: integrations.error,
    refresh: () => integrations.mutate(),
  };
}

interface AgentPreference {
  disabled_tool_ids: number[];
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
  const loaded = !enabled || data !== undefined || error !== undefined;

  const disabledPluginIds = useCallback(
    (agentId: number): string[] | null =>
      loaded ? (data?.[String(agentId)]?.disabled_plugin_ids ?? []) : null,
    [data, loaded]
  );

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
          // Not loaded: a write would replace the saved built-in tool choices.
          if (current === undefined) return current;
          const record = current?.[key];
          const saved = record?.disabled_plugin_ids ?? [];
          const next = disabled
            ? [...new Set([...saved, ...pluginIds])]
            : saved.filter((id) => !pluginIds.includes(id));
          const body: AgentPreference = {
            disabled_tool_ids: record?.disabled_tool_ids ?? [],
            disabled_plugin_ids: next,
          };
          pending.body = body;
          return { ...current, [key]: body };
        },
        { revalidate: false }
      );
      const sent = pending.body;
      if (sent === null) return;
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

  return { loaded, disabledPluginIds, setPluginsDisabled };
}
