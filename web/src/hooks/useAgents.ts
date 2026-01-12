"use client";

import useSWR from "swr";
import { useState, useEffect, useMemo, useCallback } from "react";
import {
  MinimalPersonaSnapshot,
  FullPersona,
} from "@/app/admin/assistants/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { pinAgents } from "../lib/assistants/orderAssistants";
import { useUser } from "@/components/user/UserProvider";
import { useSearchParams } from "next/navigation";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import useChatSessions from "./useChatSessions";

/**
 * Fetches all agents (personas) available to the current user.
 *
 * Returns minimal agent snapshots containing basic information like name, description,
 * tools, and display settings. Use this for listing agents in UI components like
 * sidebars, dropdowns, or agent selection interfaces.
 *
 * For full agent details including user_file_ids, groups, and advanced settings,
 * use `useAgent(personaId)` instead.
 *
 * @returns Object containing:
 *   - agents: Array of MinimalPersonaSnapshot objects (empty array while loading)
 *   - isLoading: Boolean indicating if data is being fetched
 *   - error: Any error that occurred during fetch
 *   - refresh: Function to manually revalidate the data
 *
 * @example
 * const { agents, isLoading } = useAgents();
 * if (isLoading) return <Spinner />;
 * return <AgentList agents={agents} />;
 */
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
 * Fetches a single agent (persona) by ID with full details.
 *
 * Returns complete agent information including user_file_ids, groups, system prompts,
 * and all configuration settings. Use this when you need detailed agent data for
 * editing, configuration, or displaying full agent details.
 *
 * For listing multiple agents with basic information, use `useAgents()` instead.
 *
 * @param agentId - The ID of the agent to fetch, or null to skip fetching
 * @returns Object containing:
 *   - agent: FullPersona object with complete agent details, or null if not loaded/not found
 *   - isLoading: Boolean indicating if data is being fetched (false when personaId is null)
 *   - error: Any error that occurred during fetch
 *   - refresh: Function to manually revalidate the data
 *
 * @example
 * const { agent, isLoading } = useAgent(selectedAgentId);
 * if (isLoading) return <Spinner />;
 * if (!agent) return <NotFound />;
 * return <AgentEditor agent={agent} />;
 */
export function useAgent(agentId: number | null) {
  const { data, error, mutate } = useSWR<FullPersona>(
    agentId ? `/api/persona/${agentId}` : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 60000,
    }
  );

  return {
    agent: data ?? null,
    isLoading: !error && !data && agentId !== null,
    error,
    refresh: mutate,
  };
}

/**
 * Hook that combines useAgents and usePinnedAgents to return full agent objects
 * with local state for optimistic drag-and-drop updates.
 */
export function usePinnedAgents() {
  const { user, refreshUser } = useUser();
  const { agents, isLoading: isLoadingAgents } = useAgents();

  // Local state for optimistic updates during drag-and-drop
  const [localPinnedAgents, setLocalPinnedAgents] = useState<
    MinimalPersonaSnapshot[]
  >([]);

  // Derive pinned agents from server data
  const serverPinnedAgents = useMemo(() => {
    if (agents.length === 0) return [];

    // If pinned_assistants is null/undefined (never set), show default personas
    // If it's an empty array (user explicitly unpinned all), show nothing
    const pinnedIds = user?.preferences.pinned_assistants;
    if (pinnedIds === null || pinnedIds === undefined) {
      return agents.filter(
        (agent) => agent.is_default_persona && agent.id !== 0
      );
    }

    return pinnedIds
      .map((id) => agents.find((agent) => agent.id === id))
      .filter((agent): agent is MinimalPersonaSnapshot => !!agent);
  }, [agents, user?.preferences.pinned_assistants]);

  // Sync server data → local state when server data changes
  // Only sync when agents have loaded (to avoid syncing empty during initial load)
  useEffect(() => {
    if (agents.length > 0) {
      setLocalPinnedAgents(serverPinnedAgents);
    }
  }, [serverPinnedAgents, agents.length]);

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
