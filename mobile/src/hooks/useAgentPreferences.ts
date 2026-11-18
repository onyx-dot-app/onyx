import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { QUERY_KEYS } from "@/api/query-keys";
import {
  getAgentPreferences,
  patchAgentPreferences,
  type AgentPreferences,
} from "@/api/chat/agentPreferences";
import { toast } from "@/hooks/useToast";
import { useSession } from "@/state/session";

const EMPTY_PREFERENCES: AgentPreferences = {};

/*
 * The PATCH replaces the whole record, so two in-flight writes are last-write-wins: an earlier
 * request completing second would undo the later toggle. Chaining keeps one write in flight at a
 * time. Module-scoped because the record is per-user, not per-hook-instance.
 */
let writeQueue: Promise<unknown> = Promise.resolve();

function enqueueWrite<T>(write: () => Promise<T>): Promise<T> {
  const next = writeQueue.then(write, write);
  // Keep the chain alive after a rejection so one failure can't wedge every later toggle.
  writeQueue = next.catch(() => undefined);
  return next;
}

export interface UseAgentPreferences {
  preferences: AgentPreferences;
  // An empty record reads as "nothing disabled", so a caller reconciling against it must wait.
  isLoaded: boolean;
  loadFailed: boolean;
  reload: () => void;
  disabledToolIdsFor: (agentId: number) => number[];
  disabledPluginIdsFor: (agentId: number) => string[];
  /*
   * A target, not a flip: the write re-reads the record as it runs, so a flip computed from a
   * stale render lands inverted. A tool with `pluginIds` (OpenAPI, MCP) switches those plugins;
   * a built-in tool switches itself.
   */
  setToolDisabled: (
    agentId: number,
    toolId: number,
    disabled: boolean,
    pluginIds?: string[],
  ) => Promise<void>;
}

export function useAgentPreferences(): UseAgentPreferences {
  const serverUrl = useSession((state) => state.serverUrl);
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: QUERY_KEYS.agentPreferences(serverUrl),
    // No serverUrl → `getBaseUrl()` throws, so stay idle until connected.
    enabled: serverUrl !== null,
    queryFn: ({ signal }) => getAgentPreferences(signal),
  });

  const preferences = query.data ?? EMPTY_PREFERENCES;
  const { refetch } = query;
  const reload = useCallback(() => {
    void refetch();
  }, [refetch]);

  const disabledToolIdsFor = useCallback(
    (agentId: number) => preferences[String(agentId)]?.disabled_tool_ids ?? [],
    [preferences],
  );

  const disabledPluginIdsFor = useCallback(
    (agentId: number) =>
      preferences[String(agentId)]?.disabled_plugin_ids ?? [],
    [preferences],
  );

  const setToolDisabled = useCallback(
    async (
      agentId: number,
      toolId: number,
      disabled: boolean,
      pluginIds: string[] = [],
    ) => {
      const key = QUERY_KEYS.agentPreferences(serverUrl);

      /*
       * A tap can land before the initial GET resolves, and the PATCH replaces the whole array —
       * computing it from an empty cache would re-enable everything disabled on another client.
       */
      if (queryClient.getQueryData(key) === undefined) {
        try {
          await queryClient.fetchQuery({
            queryKey: key,
            queryFn: ({ signal }) => getAgentPreferences(signal),
          });
        } catch (error) {
          console.error("Failed to load agent preferences", error);
          toast.error("Couldn't update this action.");
          return;
        }
      }

      await queryClient.cancelQueries({ queryKey: key });

      const previous = queryClient.getQueryData<AgentPreferences | null>(key);
      const currentTools = previous?.[String(agentId)]?.disabled_tool_ids ?? [];
      const currentPlugins =
        previous?.[String(agentId)]?.disabled_plugin_ids ?? [];
      let nextTools = currentTools;
      let nextPlugins = currentPlugins;
      if (pluginIds.length > 0) {
        if (pluginIds.every((id) => currentPlugins.includes(id)) === disabled) {
          return;
        }
        nextPlugins = disabled
          ? [...new Set([...currentPlugins, ...pluginIds])]
          : currentPlugins.filter((id) => !pluginIds.includes(id));
      } else {
        if (currentTools.includes(toolId) === disabled) return;
        nextTools = disabled
          ? [...currentTools, toolId]
          : currentTools.filter((id) => id !== toolId);
      }

      queryClient.setQueryData<AgentPreferences>(key, {
        ...(previous ?? EMPTY_PREFERENCES),
        [String(agentId)]: {
          disabled_tool_ids: nextTools,
          disabled_plugin_ids: nextPlugins,
        },
      });

      try {
        await enqueueWrite(async () => {
          /*
           * apiFetch resolves the base URL and bearer token when the queued write runs, so one
           * queued before a logout or instance switch would land on whoever signs in next.
           */
          if (useSession.getState().serverUrl !== serverUrl) return;
          await patchAgentPreferences(agentId, nextTools, nextPlugins);
        });
      } catch (error) {
        console.error("Failed to save agent preferences", error);
        queryClient.setQueryData(key, previous);
        toast.error("Couldn't update this action.");
      } finally {
        void queryClient.invalidateQueries({ queryKey: key });
      }
    },
    [queryClient, serverUrl],
  );

  return {
    preferences,
    isLoaded: query.isSuccess,
    loadFailed: query.isError,
    reload,
    disabledToolIdsFor,
    disabledPluginIdsFor,
    setToolDisabled,
  };
}
