"use client";

import useSWR from "swr";
import { useState, useEffect, useMemo, useCallback } from "react";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  FullAgent,
  MinimalAgent,
  Agent,
  UseAdminAgentsOptions,
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

export function useAdminAgents(options: UseAdminAgentsOptions = {}) {
  const {
    includeDeleted = false,
    getEditable = false,
    includeDefault = false,
    pageNum,
    pageSize,
  } = options;

  const usePagination = pageNum !== undefined && pageSize !== undefined;

  const url = usePagination
    ? buildApiPath("/api/admin/agents", {
        include_deleted: includeDeleted,
        get_editable: getEditable,
        include_default: includeDefault,
        page_num: pageNum,
        page_size: pageSize,
      })
    : buildApiPath("/api/admin/persona", {
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

export function useAgentController({
  selectedChatSession,
  onAgentSelect,
}: {
  selectedChatSession: ChatSession | null | undefined;
  onAgentSelect?: () => void;
}) {
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
  >(
    existingChatSessionAgentId !== undefined
      ? availableAgents.find((a) => a.id === existingChatSessionAgentId)
      : defaultAgentId !== undefined
        ? availableAgents.find((a) => a.id === defaultAgentId)
        : undefined
  );

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

export function useIsDefaultAgent({
  liveAgent,
  existingChatSessionId,
  selectedChatSession,
  settings,
}: {
  liveAgent: MinimalAgent | undefined;
  existingChatSessionId: string | null;
  selectedChatSession: ChatSession | undefined;
  settings: CombinedSettings | null;
}) {
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
