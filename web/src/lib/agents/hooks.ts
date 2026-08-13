"use client";

import useSWR, { useSWRConfig } from "swr";
import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  AgentLabel,
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
import { DEFAULT_AGENT_ID } from "@/lib/constants";
import { useSettings } from "@/lib/settings/hooks";
import {
  AgentEditorMCPServer,
  MCPServersResponse,
} from "@/lib/tools/interfaces";
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

// ── Agent resolution ──────────────────────────────────────────────────────────

/**
 * The id the user has actually landed on: the open chat's agent, or the one
 * named by the URL. `undefined` when neither applies, which is the plain
 * new-session case.
 *
 * The two inputs are disjoint in practice. `AGENT_ID` is stripped from the URL
 * the moment a chat opens (`PARAMS_TO_SKIP` in `app/app/services/lib.tsx`), so
 * a session and a URL agent never coexist under normal navigation. The session
 * is preferred anyway, for the case of a hand-written URL carrying both: the
 * messages already on screen came from the session's agent, and resolving to
 * the URL's would mislabel them.
 */
function useResolvedAgentId(): number | undefined {
  const searchParams = useSearchParams();
  const { currentChatSession } = useChatSessions();

  const urlAgentIdRaw = searchParams?.get(SEARCH_PARAM_NAMES.AGENT_ID);
  const sessionAgentId = currentChatSession?.persona_id;

  return useMemo(() => {
    if (sessionAgentId !== undefined && sessionAgentId !== null) {
      return sessionAgentId;
    }
    return urlAgentIdRaw ? parseInt(urlAgentIdRaw) : undefined;
  }, [sessionAgentId, urlAgentIdRaw]);
}

/**
 * The agent the user explicitly landed on, or null when they did not pick one.
 *
 * Use this to answer "is this agent the one in view" — highlighting a sidebar
 * entry, showing starter messages. For the agent a message would actually run
 * on, use {@link useLiveAgent}, which never returns null.
 */
export function useSelectedAgent(): MinimalAgent | null {
  const { agents } = useAgents();
  const agentId = useResolvedAgentId();

  return useMemo(() => {
    if (agentId === undefined) return null;
    return agents.find((a) => a.id === agentId) ?? null;
  }, [agents, agentId]);
}

/**
 * The agent a new message will use: the selected one, or the Assistant, or
 * whatever else is available. Unlike {@link useSelectedAgent} this always
 * answers, because every message is sent against some agent — a plain chat
 * runs on the Assistant (id 0), sent explicitly as `personaId: 0`.
 *
 * `disable_default_assistant` excludes the Assistant from the fallback, so an
 * install with no other agent resolves to `undefined` and the caller shows its
 * no-agent state rather than silently using the agent the admin disabled.
 *
 * This is a derivation, not state. Every input is shared — the URL, the open
 * session, the SWR-backed agent list — so two callers always agree, and the
 * answer re-resolves on navigation.
 */
export function useLiveAgent(): MinimalAgent | undefined {
  const selectedAgent = useSelectedAgent();
  const { agents } = useAgents();
  const settings = useSettings();
  const assistantDisabled = settings.disable_default_assistant ?? false;

  return useMemo(() => {
    // A selected id that matches no available agent falls through to the
    // fallback, which is how a deleted or inaccessible agent degrades.
    if (selectedAgent) return selectedAgent;
    if (assistantDisabled) {
      return agents.find((a) => a.id !== DEFAULT_AGENT_ID);
    }
    return agents.find((a) => a.id === DEFAULT_AGENT_ID) ?? agents[0];
  }, [selectedAgent, agents, assistantDisabled]);
}

// ── Default agent detection ───────────────────────────────────────────────────

/**
 * Whether the chat is running on the Assistant (id 0) rather than a chosen
 * agent. This is the "no particular agent" case, which the UI treats as plain
 * chat — no agent description, a generic greeting.
 *
 * Loading counts as the Assistant: it is what an unresolved chat will almost
 * always settle on, and assuming otherwise flashes a named-agent layout for an
 * agent that is not there yet.
 */
export function useIsDefaultAgent(): boolean {
  const liveAgent = useLiveAgent();
  const settings = useSettings();

  // With the Assistant disabled it is never the answer, even before the agent
  // list resolves.
  if (settings.disable_default_assistant) return false;
  return liveAgent === undefined || liveAgent.id === DEFAULT_AGENT_ID;
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

// ── Labels ────────────────────────────────────────────────────────────────────

export function useLabels() {
  const { mutate } = useSWRConfig();
  const { data: labels, error } = useSWR<AgentLabel[]>(
    SWR_KEYS.personaLabels,
    errorHandlingFetcher
  );

  const refreshLabels = async () => {
    return mutate(SWR_KEYS.personaLabels);
  };

  const createLabel = async (name: string): Promise<AgentLabel | null> => {
    const response = await fetch(SWR_KEYS.personaLabels, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });

    if (!response.ok) {
      return null;
    }

    const newLabel: AgentLabel = await response.json();
    mutate(
      SWR_KEYS.personaLabels,
      (currentLabels: AgentLabel[] | undefined) => [
        ...(currentLabels || []),
        newLabel,
      ],
      false
    );
    return newLabel;
  };

  const updateLabel = async (id: number, name: string) => {
    const response = await fetch(`/api/admin/persona/label/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label_name: name }),
    });

    if (response.ok) {
      mutate(
        SWR_KEYS.personaLabels,
        labels?.map((label) => (label.id === id ? { ...label, name } : label)),
        false
      );
    }

    return response;
  };

  const deleteLabel = async (id: number) => {
    const response = await fetch(`/api/admin/persona/label/${id}`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
    });

    if (response.ok) {
      mutate(
        SWR_KEYS.personaLabels,
        labels?.filter((label) => label.id !== id),
        false
      );
    }

    return response;
  };

  return {
    labels,
    error,
    refreshLabels,
    createLabel,
    updateLabel,
    deleteLabel,
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

export function useMcpServersForPersonaEditor(personaId: number | undefined) {
  const accessible = useMcpServersForAgentEditor();
  const {
    data: attachedData,
    error: attachedError,
    isLoading: attachedIsLoading,
  } = useSWR<MCPServersResponse>(
    personaId ? SWR_KEYS.personaMcpServers(personaId) : null,
    errorHandlingFetcher
  );

  const mcpServers = useMemo<AgentEditorMCPServer[]>(() => {
    const accessibleServers = accessible.mcpData?.mcp_servers ?? [];
    const accessibleIds = new Set(accessibleServers.map((server) => server.id));
    return [
      ...accessibleServers.map((server) => ({ ...server, can_attach: true })),
      ...(attachedData?.mcp_servers ?? [])
        .filter((server) => !accessibleIds.has(server.id))
        .map((server) => ({ ...server, can_attach: false })),
    ];
  }, [accessible.mcpData, attachedData]);

  return {
    mcpServers,
    isLoading:
      accessible.isLoading || (personaId !== undefined && attachedIsLoading),
    error: accessible.error || attachedError,
  };
}
