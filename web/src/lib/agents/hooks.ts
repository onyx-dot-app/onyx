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
 * The agent named by where the user is: the open chat's agent, or the URL's
 * `agentId`. `undefined` when neither names one, which is the plain
 * new-session case.
 *
 * The two are disjoint in practice. `AGENT_ID` is stripped from the URL the
 * moment a chat opens (`PARAMS_TO_SKIP` in `app/app/services/lib.tsx`), so a
 * session and a URL agent never coexist under normal navigation. The session
 * is preferred anyway, for a hand-written URL carrying both: the messages
 * already on screen came from the session's agent, and resolving to the URL's
 * would mislabel them.
 */
function useAddressedAgentId(): number | undefined {
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
 * The agent this chat is running on. There is no agent-less chat — every
 * message is sent against one, and a plain chat is the Assistant, sent
 * explicitly as `personaId: 0`. So this answers whenever any agent is
 * available, and `undefined` means the list has not loaded or nothing is
 * eligible, not "no agent".
 *
 * Resolution, first match wins:
 *
 * 1. the agent the location names — the open session's, or the URL's
 * 2. the Assistant, when eligible — the plain-chat default
 * 3. the first pinned agent, which for a user with no pins of their own is the
 *    first *featured* agent. This is what "Set featured agents to help new
 *    users get started" means: with the Assistant disabled, steps 1 and 2 both
 *    miss and featured agents are what a new user lands on.
 * 4. anything eligible
 *
 * "Always Start with an Agent" (`disable_default_assistant`) is a constraint,
 * not a preference: with it on the Assistant is never a valid answer, so it
 * leaves the candidate set up front rather than being skipped at step 2. That
 * is what stops a stale `?agentId=0`, or a session created before the setting
 * was enabled, from routing back to it.
 *
 * An id that matches no eligible agent falls through, which is how a deleted,
 * inaccessible, or disabled agent degrades.
 *
 * This is a derivation, not state, so it re-resolves on navigation rather than
 * latching. Its inputs are shared — the URL, the open session, the SWR-backed
 * agent list — with one exception: {@link usePinnedAgents} keeps an optimistic
 * copy per hook instance, so during the moment after a pin toggle two callers
 * can disagree on step 3. Steps 1 and 2 answer in every ordinary case.
 */
export function useActiveAgent(): MinimalAgent | undefined {
  const { agents } = useAgents();
  const { pinnedAgents } = usePinnedAgents();
  const settings = useSettings();
  const addressedAgentId = useAddressedAgentId();
  const assistantDisabled = settings.disable_default_assistant ?? false;

  return useMemo(() => {
    // The constraint leaves the candidate set before anything is resolved, so
    // no later step can reach the Assistant by another route.
    const eligible = assistantDisabled
      ? agents.filter((agent) => agent.id !== DEFAULT_AGENT_ID)
      : agents;

    const addressed = eligible.find((a) => a.id === addressedAgentId);
    if (addressed) return addressed;

    const assistant = eligible.find((a) => a.id === DEFAULT_AGENT_ID);
    if (assistant) return assistant;

    const pinned = pinnedAgents.find((pinnedAgent) =>
      eligible.some((a) => a.id === pinnedAgent.id)
    );
    return pinned ?? eligible[0];
  }, [agents, assistantDisabled, pinnedAgents, addressedAgentId]);
}

/**
 * Where "New Session" goes.
 *
 * Normally a bare new chat, which lands on the Assistant. With
 * "Always Start with an Agent" there is no such chat to land on, so the link
 * names an agent outright — the one already in view, or the featured agent a
 * new user should start in. {@link useActiveAgent} answers both.
 */
export function useNewSessionHref(): string {
  const activeAgent = useActiveAgent();
  const settings = useSettings();

  if (!settings.disable_default_assistant || !activeAgent) return "/app";
  return `/app?${SEARCH_PARAM_NAMES.AGENT_ID}=${activeAgent.id}`;
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
    SWR_KEYS.agentLabels,
    errorHandlingFetcher
  );

  const refreshLabels = async () => {
    return mutate(SWR_KEYS.agentLabels);
  };

  const createLabel = async (name: string): Promise<AgentLabel | null> => {
    const response = await fetch(SWR_KEYS.agentLabels, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });

    if (!response.ok) {
      return null;
    }

    const newLabel: AgentLabel = await response.json();
    mutate(
      SWR_KEYS.agentLabels,
      (currentLabels: AgentLabel[] | undefined) => [
        ...(currentLabels || []),
        newLabel,
      ],
      false
    );
    return newLabel;
  };

  const updateLabel = async (id: number, name: string) => {
    const response = await fetch(SWR_KEYS.adminAgentLabel(id), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label_name: name }),
    });

    if (response.ok) {
      mutate(
        SWR_KEYS.agentLabels,
        labels?.map((label) => (label.id === id ? { ...label, name } : label)),
        false
      );
    }

    return response;
  };

  const deleteLabel = async (id: number) => {
    const response = await fetch(SWR_KEYS.adminAgentLabel(id), {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
    });

    if (response.ok) {
      mutate(
        SWR_KEYS.agentLabels,
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

/** Every MCP server the current user can reach. */
export function useMcpServers() {
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

export function useMcpServersForAgent(agentId: number | undefined) {
  const accessible = useMcpServers();
  const {
    data: attachedData,
    error: attachedError,
    isLoading: attachedIsLoading,
  } = useSWR<MCPServersResponse>(
    agentId ? SWR_KEYS.agentMcpServers(agentId) : null,
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
      accessible.isLoading || (agentId !== undefined && attachedIsLoading),
    error: accessible.error || attachedError,
  };
}
