"use client";

import useSWR, { useSWRConfig } from "swr";
import { useState, useEffect, useMemo, useCallback } from "react";
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
    SWR_KEYS.agents,
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
    agentId ? SWR_KEYS.agent(agentId) : null,
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
 * The agents pinned to the sidebar, and the writes that reorder or toggle them.
 *
 * A user with no pins has none — there is no featured-agent fallback here.
 * Featured agents reach a new user by seeding their pins at account creation,
 * server-side, so by the time this reads them they are ordinary pins.
 *
 * Writes apply locally before the server confirms. That optimistic copy lives
 * per hook instance rather than in shared state, so between a toggle and the
 * user refresh that follows it, two components calling this hook can briefly
 * disagree about what is pinned.
 */
export function usePinnedAgents() {
  const { user, refreshUser } = useUser();
  const { agents, isLoading: isLoadingAgents } = useAgents();

  const [localPinnedAgents, setLocalPinnedAgents] = useState<MinimalAgent[]>(
    []
  );

  const serverPinnedAgents = useMemo(() => {
    if (agents.length === 0) return [];
    const pinnedIds = user?.preferences.pinned_assistants ?? [];
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
 * The agent this chat is running on. There is no agent-less chat — every
 * message is sent against one, and a plain chat is the Assistant, sent
 * explicitly as `personaId: 0`. So this answers whenever any agent is
 * available, and `undefined` means the list has not loaded or nothing is
 * eligible, not "no agent".
 *
 * Resolution, first match wins:
 *
 * 1. the agent the location names — the open session's, or the URL's. These
 *    are disjoint in practice: `AGENT_ID` is stripped from the URL the moment
 *    a chat opens (`PARAMS_TO_SKIP` in `app/app/services/lib.tsx`). The session
 *    wins anyway, for a hand-written URL carrying both — the messages already
 *    on screen came from the session's agent, and the URL's would mislabel
 *    them.
 * 2. the Assistant, when eligible — the plain-chat default
 * 3. the first pinned agent. A new user's pins are seeded from the featured
 *    agents at account creation, which is what "Set featured agents to help new
 *    users get started" means — by the time this runs they are ordinary pins.
 *    A user who has unpinned everything has nothing here and falls to step 4.
 * 4. anything eligible
 *
 * "Disable Default Chat" (`disable_default_assistant`) is a constraint,
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
  const searchParams = useSearchParams();
  const { currentChatSession } = useChatSessions();

  const assistantDisabled = settings.disable_default_assistant ?? false;
  const urlAgentIdRaw = searchParams?.get(SEARCH_PARAM_NAMES.AGENT_ID);
  const sessionAgentId = currentChatSession?.persona_id;

  return useMemo(() => {
    // The constraint leaves the candidate set before anything is resolved, so
    // no later step can reach the Assistant by another route.
    const eligible = assistantDisabled
      ? agents.filter((agent) => agent.id !== DEFAULT_AGENT_ID)
      : agents;

    const namedId =
      sessionAgentId ?? (urlAgentIdRaw ? parseInt(urlAgentIdRaw) : undefined);
    const named = eligible.find((agent) => agent.id === namedId);
    if (named) return named;

    const assistant = eligible.find((agent) => agent.id === DEFAULT_AGENT_ID);
    if (assistant) return assistant;

    const pinned = pinnedAgents.find((pinnedAgent) =>
      eligible.some((agent) => agent.id === pinnedAgent.id)
    );
    return pinned ?? eligible[0];
  }, [agents, assistantDisabled, pinnedAgents, sessionAgentId, urlAgentIdRaw]);
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

// ── Agent Labels ──────────────────────────────────────────────────────────────

export function useAgentLabels() {
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
