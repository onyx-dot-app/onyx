import useSWR from "swr";
import { useState, useEffect, useRef, useMemo } from "react";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { pinAgents } from "../assistants/orderAssistants";

export function useAgents() {
  const { data, error, mutate } = useSWR<MinimalPersonaSnapshot[]>(
    "/api/persona",
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 60000,
    }
  );

  return {
    agents: data ?? [],
    isLoading: !error && !data,
    error,
    refresh: mutate,
  };
}

export function usePinnedAgents() {
  const { data, error, mutate } = useSWR<number[]>(
    "/api/user/pinned-assistants",
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 60000,
    }
  );

  return {
    pinnedAgentIds: data ?? [],
    isLoading: !error && !data,
    error,
    refresh: mutate,
  };
}

/**
 * Hook that combines useAgents and usePinnedAgents to return full agent objects
 * with local state for optimistic drag-and-drop updates.
 */
export function usePinnedAgentsWithDetails() {
  const { agents, isLoading: isLoadingAgents } = useAgents();
  const {
    pinnedAgentIds,
    isLoading: isLoadingPinned,
    refresh,
  } = usePinnedAgents();

  // Local state for optimistic updates during drag-and-drop
  const [localPinnedAgents, setLocalPinnedAgents] = useState<
    MinimalPersonaSnapshot[]
  >([]);
  const isInitialMount = useRef(true);

  // Derive pinned agents from server data
  const serverPinnedAgents = useMemo(() => {
    if (agents.length === 0) return [];

    const pinned = pinnedAgentIds
      .map((id) => agents.find((agent) => agent.id === id))
      .filter((agent): agent is MinimalPersonaSnapshot => !!agent);

    // Fallback to default personas if no pinned agents
    return pinned.length > 0
      ? pinned
      : agents.filter((agent) => agent.is_default_persona && agent.id !== 0);
  }, [agents, pinnedAgentIds]);

  // Sync server data → local state when server data changes
  useEffect(() => {
    if (serverPinnedAgents.length > 0) {
      setLocalPinnedAgents(serverPinnedAgents);
    }
  }, [serverPinnedAgents]);

  // Persist to server when local state changes (after initial mount)
  useEffect(() => {
    if (isInitialMount.current) {
      isInitialMount.current = false;
      return;
    }
    if (localPinnedAgents.length > 0) {
      pinAgents(localPinnedAgents.map((a) => a.id)).then(() => refresh());
    }
  }, [localPinnedAgents, refresh]);

  return {
    pinnedAgents: localPinnedAgents,
    setPinnedAgents: setLocalPinnedAgents,
    isLoading: isLoadingAgents || isLoadingPinned,
  };
}
