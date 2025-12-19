import useSWR from "swr";
import { useState, useEffect, useMemo, useCallback } from "react";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { pinAgents } from "../lib/assistants/orderAssistants";
import { useUser } from "@/components/user/UserProvider";
import { useSearchParams } from "next/navigation";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import useChatSessions from "./useChatSessions";

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

/**
 * Hook that combines useAgents and usePinnedAgents to return full agent objects
 * with local state for optimistic drag-and-drop updates.
 */
export function usePinnedAgentsWithDetails() {
  const { user, refreshUser } = useUser();
  const { agents, isLoading: isLoadingAgents } = useAgents();

  // Local state for optimistic updates during drag-and-drop
  const [localPinnedAgents, setLocalPinnedAgents] = useState<
    MinimalPersonaSnapshot[]
  >([]);

  // Derive pinned agents from server data
  const serverPinnedAgents = useMemo(() => {
    if (agents.length === 0) return [];

    const pinned = (user?.preferences.pinned_assistants ?? [])
      .map((id) => agents.find((agent) => agent.id === id))
      .filter((agent): agent is MinimalPersonaSnapshot => !!agent);

    // Fallback to default personas if no pinned agents
    return pinned.length > 0
      ? pinned
      : agents.filter((agent) => agent.is_default_persona && agent.id !== 0);
  }, [agents, user?.preferences.pinned_assistants]);

  // Sync server data → local state when server data changes
  useEffect(() => {
    if (serverPinnedAgents.length > 0) {
      setLocalPinnedAgents(serverPinnedAgents);
    }
  }, [serverPinnedAgents]);

  // Toggle pin status - updates local state AND persists to server
  const togglePinnedAgent = useCallback(
    async (agent: MinimalPersonaSnapshot, shouldPin: boolean) => {
      const newPinned = shouldPin
        ? [...localPinnedAgents, agent]
        : localPinnedAgents.filter((a) => a.id !== agent.id);

      // Optimistic update
      setLocalPinnedAgents(newPinned);

      // Persist to server
      await pinAgents(newPinned.map((a) => a.id));
      refreshUser(); // Refresh user to sync pinned_assistants
    },
    [localPinnedAgents, refreshUser]
  );

  // Update pinned agents order (for drag-and-drop) - updates AND persists
  const updatePinnedAgents = useCallback(
    async (newPinnedAgents: MinimalPersonaSnapshot[]) => {
      // Optimistic update
      setLocalPinnedAgents(newPinnedAgents);

      // Persist to server
      await pinAgents(newPinnedAgents.map((a) => a.id));
      refreshUser();
    },
    [refreshUser]
  );

  return {
    pinnedAgents: localPinnedAgents,
    togglePinnedAgent,
    updatePinnedAgents, // Use this instead of setPinnedAgents for drag-and-drop
    isLoading: isLoadingAgents,
  };
}

/**
 * Hook to determine the currently active agent based on:
 * 1. URL param `assistantId`
 * 2. Chat session's `persona_id`
 * 3. Falls back to null if neither is present
 */
export function useCurrentAgent(): MinimalPersonaSnapshot | null {
  const { agents } = useAgents();
  const searchParams = useSearchParams();

  const agentIdRaw = searchParams?.get(SEARCH_PARAM_NAMES.PERSONA_ID);
  const { currentChatSession } = useChatSessions();

  const currentAgent = useMemo(() => {
    if (agents.length === 0) return null;

    // Priority: URL param > chat session persona > null
    const agentId = agentIdRaw
      ? parseInt(agentIdRaw)
      : currentChatSession?.persona_id;

    if (!agentId) return null;

    return agents.find((a) => a.id === agentId) ?? null;
  }, [agents, agentIdRaw, currentChatSession?.persona_id]);

  return currentAgent;
}
