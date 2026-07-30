import { useCallback, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/api/client";
import { QUERY_KEYS } from "@/api/query-keys";
import {
  DEFAULT_AGENT_ID,
  MinimalAgent,
  resolvePinnedAgents,
} from "@/chat/agents";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { useSession } from "@/state/session";

export function useAgents() {
  const serverUrl = useSession((state) => state.serverUrl);
  const query = useQuery({
    queryKey: QUERY_KEYS.agents(serverUrl),
    // No serverUrl → `getBaseUrl()` throws, so stay idle until connected.
    enabled: serverUrl !== null,
    queryFn: ({ signal }) => apiFetch<MinimalAgent[]>("/persona", { signal }),
  });
  return { ...query, agents: query.data ?? [] };
}

// Sidebar rail agents (see resolvePinnedAgents) + an auto-pin action.
export function usePinnedAgents() {
  const { agents } = useAgents();
  const { data: user } = useCurrentUser();
  const serverUrl = useSession((state) => state.serverUrl);
  const queryClient = useQueryClient();

  const pinnedIds = user?.preferences.pinned_assistants;

  const pinnedAgents = useMemo<MinimalAgent[]>(
    () => resolvePinnedAgents(agents, pinnedIds),
    [agents, pinnedIds],
  );

  // Append to the pinned list and PATCH the full ordered ids, then refetch the user.
  // Never pins id 0; best-effort.
  const ensurePinned = useCallback(
    async (agent: MinimalAgent) => {
      if (agent.id === DEFAULT_AGENT_ID) return;
      if (pinnedAgents.some((a) => a.id === agent.id)) return;
      const orderedIds = [...pinnedAgents.map((a) => a.id), agent.id];
      try {
        await apiFetch<void>("/user/pinned-assistants", {
          method: "PATCH",
          body: { ordered_assistant_ids: orderedIds },
        });
        await queryClient.invalidateQueries({
          queryKey: QUERY_KEYS.me(serverUrl),
        });
      } catch {
        // best-effort
      }
    },
    [pinnedAgents, queryClient, serverUrl],
  );

  return { pinnedAgents, ensurePinned };
}
