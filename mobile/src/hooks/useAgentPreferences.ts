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

// The PATCH replaces the whole record, so two in-flight writes are last-write-wins: an earlier
// request completing second would undo the later toggle. Chaining keeps one write in flight at a
// time. Module-scoped because the record is per-user, not per-hook-instance.
let writeQueue: Promise<unknown> = Promise.resolve();

function enqueueWrite<T>(write: () => Promise<T>): Promise<T> {
  const next = writeQueue.then(write, write);
  // Keep the chain alive after a rejection so one failure can't wedge every later toggle.
  writeQueue = next.catch(() => undefined);
  return next;
}

export interface UseAgentPreferences {
  preferences: AgentPreferences;
  disabledToolIdsFor: (agentId: number) => number[];
  // Optimistic; rolls back and toasts if the PATCH fails.
  toggleDisabledTool: (agentId: number, toolId: number) => Promise<void>;
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

  const disabledToolIdsFor = useCallback(
    (agentId: number) => preferences[String(agentId)]?.disabled_tool_ids ?? [],
    [preferences],
  );

  const toggleDisabledTool = useCallback(
    async (agentId: number, toolId: number) => {
      const key = QUERY_KEYS.agentPreferences(serverUrl);

      // A tap can land before the initial GET resolves, and the PATCH replaces the whole array —
      // computing it from an empty cache would re-enable everything disabled on another client.
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

      // Live cache, not a render-time snapshot, so concurrent toggles compose instead of racing.
      const previous = queryClient.getQueryData<AgentPreferences | null>(key);
      const current = previous?.[String(agentId)]?.disabled_tool_ids ?? [];
      const next = current.includes(toolId)
        ? current.filter((id) => id !== toolId)
        : [...current, toolId];

      queryClient.setQueryData<AgentPreferences>(key, {
        ...(previous ?? EMPTY_PREFERENCES),
        [String(agentId)]: { disabled_tool_ids: next },
      });

      try {
        await enqueueWrite(async () => {
          // The queue defers this, and apiFetch resolves the base URL and bearer token only when
          // it finally runs — so a write queued before a logout or instance switch would land on
          // whoever is signed in by then. Drop it instead.
          if (useSession.getState().serverUrl !== serverUrl) return;
          await patchAgentPreferences(agentId, next);
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

  return { preferences, disabledToolIdsFor, toggleDisabledTool };
}
