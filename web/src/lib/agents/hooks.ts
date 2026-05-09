"use client";

import useSWR from "swr";
import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  FullAgent,
  MinimalAgent,
  Agent,
  PaginatedAgentsResponse,
} from "@/lib/agents/types";
import {
  UserSpecificAgentPreference,
  UserSpecificAgentPreferences,
} from "@/lib/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { buildApiPath } from "@/lib/urlBuilder";
import { pinAgents } from "@/lib/agents/svc";
import { useUser } from "@/providers/UserProvider";
import { useSearchParams } from "next/navigation";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import { CombinedSettings } from "@/interfaces/settings";
import { ChatSession } from "@/app/app/interfaces";
import { DEFAULT_AGENT_ID } from "@/lib/constants";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { MCPServersResponse } from "@/lib/tools/interfaces";
import useChatSessions from "@/hooks/useChatSessions";
import { buildUpdateAgentPreferenceUrl } from "./utils";

// ── Data fetching ─────────────────────────────────────────────────────────────

/**
 * Fetches the full list of agents visible to the current user.
 * Results are deduplicated for 60 s and not revalidated on focus to avoid
 * redundant round-trips across the app.
 */
export function useAgents() {
  const { data, error, mutate } = useSWR<MinimalAgent[]>(
    SWR_KEYS.personas,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateIfStale: false,
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
 * Fetches a single agent by ID. Passing null skips the request entirely,
 * which is useful when the agent ID isn't known yet.
 */
export function useAgent(agentId: number | null) {
  const { data, error, isLoading, mutate } = useSWR<FullAgent>(
    agentId ? SWR_KEYS.persona(agentId) : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateIfStale: false,
      dedupingInterval: 60000,
    }
  );

  return {
    agent: data ?? null,
    isLoading,
    error,
    refresh: mutate,
  };
}

/**
 * Fetches agents for the admin panel. Supports optional server-side
 * pagination — when pageNum and pageSize are both provided, the response is
 * paginated and totalItems reflects the full count; otherwise all agents are
 * returned in a flat array.
 */
export function useAdminAgents(
  includeDeleted = false,
  getEditable = false,
  includeDefault = false,
  pageNum?: number,
  pageSize?: number
) {
  const usePagination = pageNum !== undefined && pageSize !== undefined;

  const url = usePagination
    ? buildApiPath(SWR_KEYS.adminAgents, {
        include_deleted: includeDeleted,
        get_editable: getEditable,
        include_default: includeDefault,
        page_num: pageNum,
        page_size: pageSize,
      })
    : buildApiPath(SWR_KEYS.adminPersona, {
        include_deleted: includeDeleted,
        get_editable: getEditable,
      });

  const { data, error, isLoading, mutate } = useSWR<
    Agent[] | PaginatedAgentsResponse
  >(url, errorHandlingFetcher);

  const agents = usePagination
    ? (data as PaginatedAgentsResponse)?.items || []
    : (data as Agent[]) || [];

  const totalItems = usePagination
    ? (data as PaginatedAgentsResponse)?.total_items || 0
    : agents.length;

  return { agents, totalItems, error, isLoading, refresh: mutate };
}

// ── Pinned agents ─────────────────────────────────────────────────────────────

/**
 * Manages the user's pinned agent list with optimistic local state.
 * When the user has no explicit pins, falls back to featured agents
 * (excluding the default agent at id=0).
 */
export function usePinnedAgents() {
  const { user, refreshUser } = useUser();
  const { agents, isLoading: isLoadingAgents } = useAgents();

  const [localPinnedAgents, setLocalPinnedAgents] = useState<MinimalAgent[]>(
    []
  );

  const serverPinnedAgents = useMemo(() => {
    if (agents.length === 0) return [];
    const pinnedIds = user?.preferences.pinned_assistants;
    if (pinnedIds === null || pinnedIds === undefined) {
      return agents.filter((agent) => agent.is_featured && agent.id !== 0);
    }
    return pinnedIds
      .map((id) => agents.find((agent) => agent.id === id))
      .filter((agent): agent is MinimalAgent => !!agent);
  }, [agents, user?.preferences.pinned_assistants]);

  useEffect(() => {
    if (agents.length > 0) {
      setLocalPinnedAgents(serverPinnedAgents);
    }
  }, [serverPinnedAgents, agents.length]);

  const togglePinnedAgent = useCallback(
    async (agent: MinimalAgent, shouldPin: boolean) => {
      const newPinned = shouldPin
        ? [...localPinnedAgents, agent]
        : localPinnedAgents.filter((a) => a.id !== agent.id);
      setLocalPinnedAgents(newPinned);
      await pinAgents(newPinned.map((a) => a.id));
      refreshUser();
    },
    [localPinnedAgents, refreshUser]
  );

  const updatePinnedAgents = useCallback(
    async (newPinnedAgents: MinimalAgent[]) => {
      setLocalPinnedAgents(newPinnedAgents);
      await pinAgents(newPinnedAgents.map((a) => a.id));
      refreshUser();
    },
    [refreshUser]
  );

  return {
    pinnedAgents: localPinnedAgents,
    togglePinnedAgent,
    updatePinnedAgents,
    isLoading: isLoadingAgents,
  };
}

// ── Current agent (URL param or chat session) ─────────────────────────────────

/**
 * Resolves the active agent from the URL search param, falling back to the
 * agent attached to the current chat session. Returns null when neither is
 * available or the agent list hasn't loaded yet.
 */
export function useCurrentAgent(): MinimalAgent | null {
  const { agents } = useAgents();
  const searchParams = useSearchParams();
  const agentIdRaw = searchParams?.get(SEARCH_PARAM_NAMES.PERSONA_ID);
  const { currentChatSession } = useChatSessions();

  return useMemo(() => {
    if (agents.length === 0) return null;
    const agentId = agentIdRaw
      ? parseInt(agentIdRaw)
      : currentChatSession?.persona_id;
    if (!agentId) return null;
    return agents.find((a) => a.id === agentId) ?? null;
  }, [agents, agentIdRaw, currentChatSession?.persona_id]);
}

// ── Agent controller (chat UI selection) ──────────────────────────────────────

/**
 * Manages agent selection state for the chat UI. `liveAgent` is the agent
 * that will actually be used for a new message, resolved by priority:
 * explicit user selection → URL param → first pinned → first available.
 * When `disable_default_assistant` is on, the built-in default (id=0) is
 * skipped in the fallback chain.
 */
export function useAgentController(
  selectedChatSession: ChatSession | null | undefined,
  onAgentSelect?: () => void
) {
  const searchParams = useSearchParams();
  const { agents: availableAgents } = useAgents();
  const { pinnedAgents } = usePinnedAgents();
  const combinedSettings = useSettingsContext();

  const defaultAgentIdRaw = searchParams?.get(SEARCH_PARAM_NAMES.PERSONA_ID);
  const defaultAgentId = defaultAgentIdRaw
    ? parseInt(defaultAgentIdRaw)
    : undefined;

  const existingChatSessionAgentId = selectedChatSession?.persona_id;
  const [selectedAgent, setSelectedAssistant] = useState<
    MinimalAgent | undefined
  >(undefined);

  // The agents list loads asynchronously, so a useState initializer would
  // always see an empty array. This effect runs the same logic once agents
  // are available, and never again (agentsLoadedRef guard) so it doesn't
  // override explicit user selections made via setSelectedAgentFromId.
  const agentsLoadedRef = useRef(false);
  useEffect(() => {
    if (agentsLoadedRef.current || availableAgents.length === 0) return;
    agentsLoadedRef.current = true;
    setSelectedAssistant(
      existingChatSessionAgentId !== undefined
        ? availableAgents.find((a) => a.id === existingChatSessionAgentId)
        : defaultAgentId !== undefined
          ? availableAgents.find((a) => a.id === defaultAgentId)
          : undefined
    );
  }, [availableAgents, existingChatSessionAgentId, defaultAgentId]);

  const liveAgent: MinimalAgent | undefined = useMemo(() => {
    if (selectedAgent) return selectedAgent;
    const disableDefaultAssistant =
      combinedSettings?.settings?.disable_default_assistant ?? false;
    if (disableDefaultAssistant) {
      const nonDefaultPinned = pinnedAgents.filter((a) => a.id !== 0);
      const nonDefaultAvailable = availableAgents.filter((a) => a.id !== 0);
      return (
        nonDefaultPinned[0] || nonDefaultAvailable[0] || availableAgents[0]
      );
    }
    const unifiedAgent = availableAgents.find((a) => a.id === 0);
    if (unifiedAgent) return unifiedAgent;
    return pinnedAgents[0] || availableAgents[0];
  }, [selectedAgent, pinnedAgents, availableAgents, combinedSettings]);

  const setSelectedAgentFromId = useCallback(
    (agentId: number | null | undefined) => {
      let newAssistant =
        agentId !== null
          ? availableAgents.find((a) => a.id === agentId)
          : undefined;
      if (!newAssistant && defaultAgentId !== undefined) {
        newAssistant = availableAgents.find((a) => a.id === defaultAgentId);
      }
      setSelectedAssistant(newAssistant);
      onAgentSelect?.();
    },
    [availableAgents, defaultAgentId, onAgentSelect]
  );

  return { selectedAgent, setSelectedAgentFromId, liveAgent };
}

// ── Default agent detection ───────────────────────────────────────────────────

/**
 * Returns true when the session is using the built-in default agent (id=0).
 * Accounts for the URL param, the existing session's agent, and the
 * `disable_default_assistant` setting which forces a non-default agent.
 */
export function useIsDefaultAgent(
  liveAgent: MinimalAgent | undefined,
  existingChatSessionId: string | null,
  selectedChatSession: ChatSession | undefined,
  settings: CombinedSettings | null
) {
  const searchParams = useSearchParams();
  const urlAssistantId = searchParams?.get(SEARCH_PARAM_NAMES.PERSONA_ID);

  return useMemo(() => {
    if (settings?.settings?.disable_default_assistant) return false;
    if (
      urlAssistantId !== null &&
      urlAssistantId !== DEFAULT_AGENT_ID.toString()
    )
      return false;
    if (
      existingChatSessionId &&
      selectedChatSession?.persona_id !== DEFAULT_AGENT_ID
    )
      return false;
    if (liveAgent !== undefined && liveAgent.id !== DEFAULT_AGENT_ID)
      return false;
    return true;
  }, [
    settings?.settings?.disable_default_assistant,
    urlAssistantId,
    existingChatSessionId,
    selectedChatSession?.persona_id,
    liveAgent?.id,
  ]);
}

// ── Agent preferences ─────────────────────────────────────────────────────────

/**
 * Fetches and updates per-user preferences for each agent (e.g. temperature
 * overrides, custom instructions). Applies an optimistic local update before
 * the server confirms to keep the UI responsive.
 */
export function useAgentPreferences() {
  const { data, mutate } = useSWR<UserSpecificAgentPreferences>(
    SWR_KEYS.agentPreferences,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateIfStale: false,
      dedupingInterval: 60000,
    }
  );

  const setSpecificAgentPreferences = useCallback(
    async (
      agentId: number,
      newAgentPreference: UserSpecificAgentPreference
    ) => {
      mutate({ ...data, [agentId]: newAgentPreference }, false);
      try {
        const response = await fetch(buildUpdateAgentPreferenceUrl(agentId), {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(newAgentPreference),
        });
        if (!response.ok) {
          console.error(
            `Failed to update agent preferences: ${response.status}`
          );
        }
      } catch (error) {
        console.error("Error updating agent preferences:", error);
      }
      mutate();
    },
    [data, mutate]
  );

  return {
    agentPreferences: data ?? null,
    setSpecificAgentPreferences,
  };
}

// ── MCP servers for agent editor ──────────────────────────────────────────────

/** Fetches the list of MCP servers for display in the agent editor's tool selector. */
export function useMcpServersForAgentEditor() {
  const {
    data: mcpData,
    error,
    isLoading,
    mutate: mutateMcpServers,
  } = useSWR<MCPServersResponse>(SWR_KEYS.mcpServers, errorHandlingFetcher);

  return {
    mcpData: mcpData ?? null,
    isLoading,
    error,
    mutateMcpServers,
  };
}
