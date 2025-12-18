"use client";

/**
 * AgentsContext
 *
 * Provides agent data plus pinning helpers for components that need to read or
 * mutate assistant ordering without prop-drilling.
 *
 * This context should be provided at the app-level (it transcends chat-sessions, namely).
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
import useSWR from "swr";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { pinAgents } from "@/lib/assistants/orderAssistants";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useUser } from "@/components/user/UserProvider";
import { useSearchParams } from "next/navigation";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";

interface AgentsContextValue {
  /** All assistants from `/api/persona`; use for lookups and listings. */
  agents: MinimalPersonaSnapshot[];

  /** Assistants currently pinned, in display order (optimistic). */
  pinnedAgents: MinimalPersonaSnapshot[];

  /** Ids of pinned assistants for lightweight checks. */
  pinnedAgentIds: number[];

  /** True while the initial agents list is still loading. */
  isLoading: boolean;

  /** Agent resolved from the `assistantId` URL param if present; null when missing or not found. */
  currentAgent: MinimalPersonaSnapshot | null;

  /** Parsed `agentId` from URL when present; `null` otherwise.
   *
   * If you want to access the agent-id for a specific chat-session, use `ChatSessionContext`'s `agentForCurrentChatSession` instead!
   */
  currentAgentId: number | null;

  /** SWR mutate for the agents list; call after server-side changes to assistants. */
  refreshAgents: () => Promise<MinimalPersonaSnapshot[] | undefined>;

  /** Refreshes user data to re-pull pinned ids from `/me` (used after pin/unpin elsewhere). */
  refreshPinnedAgents: () => Promise<void>;

  /** Pin/unpin an agent with optimistic UI updates; persists via `pinAgents`. */
  togglePinnedAgent: (agentId: number, shouldPin: boolean) => Promise<void>;

  /** Replace/reorder the entire pinned list (e.g., drag-and-drop); persists and updates local state. */
  updatePinnedAgents: (agentIds: number[]) => Promise<void>;
}

const AgentsContext = createContext<AgentsContextValue | undefined>(undefined);

interface AgentsProviderProps {
  children: ReactNode;
}

export function AgentsProvider({ children }: AgentsProviderProps) {
  const {
    data: agentsData,
    error,
    mutate: refreshAgents,
  } = useSWR<MinimalPersonaSnapshot[]>("/api/persona", errorHandlingFetcher, {
    revalidateOnFocus: false,
    dedupingInterval: 60000,
  });

  const { user, refreshUser } = useUser();

  const agents = agentsData ?? [];
  const isLoadingAgents = !error && !agentsData;
  const searchParams = useSearchParams();

  const serverPinnedAgentIds = user?.preferences?.pinned_assistants ?? [];

  const serverPinnedAgents = useMemo(() => {
    if (agents.length === 0) return [];

    const pinned = serverPinnedAgentIds
      .map((pinnedAgentId) =>
        agents.find((agent) => agent.id === pinnedAgentId)
      )
      .filter((agent): agent is MinimalPersonaSnapshot => !!agent);

    return pinned.length > 0
      ? pinned
      : agents.filter((agent) => agent.is_default_persona && agent.id !== 0);
  }, [agents, serverPinnedAgentIds]);

  // Local pinned state for optimistic updates and drag-and-drop ordering.
  const [localPinnedAgents, setLocalPinnedAgents] = useState<
    MinimalPersonaSnapshot[]
  >(() => serverPinnedAgents);

  // Keep local state in sync with server-derived pinned agents when data changes.
  useEffect(
    () => setLocalPinnedAgents(serverPinnedAgents),
    [serverPinnedAgents]
  );

  const currentAgent = useMemo(() => {
    const agentIdRaw = searchParams?.get(SEARCH_PARAM_NAMES.PERSONA_ID);
    const agentId = agentIdRaw ? parseInt(agentIdRaw, 10) : NaN;
    if (Number.isNaN(agentId)) return null;
    return agents.find((agent) => agent.id === agentId) ?? null;
  }, [agents, searchParams]);

  const persistPins = useCallback(
    async (pinnedIds: number[]) => {
      await pinAgents(pinnedIds);
      await refreshUser();
    },
    [refreshUser]
  );

  const togglePinnedAgent = useCallback(
    async (agentId: number, shouldPin: boolean) => {
      const agent = agents.find((a) => a.id === agentId);
      if (!agent) return;

      const nextPinned = shouldPin
        ? [...localPinnedAgents, agent]
        : localPinnedAgents.filter((a) => a.id !== agentId);

      const previousPinned = localPinnedAgents;
      setLocalPinnedAgents(nextPinned);

      try {
        await persistPins(nextPinned.map((a) => a.id));
      } catch (error) {
        // Rollback optimistic update on error
        setLocalPinnedAgents(previousPinned);
        throw error;
      }
    },
    [agents, localPinnedAgents, persistPins]
  );

  const updatePinnedAgents = useCallback(
    async (agentIds: number[]) => {
      const nextPinned = agentIds
        .map((id) => agents.find((agent) => agent.id === id))
        .filter((agent): agent is MinimalPersonaSnapshot => !!agent);

      const previousPinned = localPinnedAgents;
      setLocalPinnedAgents(nextPinned);

      try {
        await persistPins(nextPinned.map((a) => a.id));
      } catch (error) {
        // Rollback optimistic update on error
        setLocalPinnedAgents(previousPinned);
        throw error;
      }
    },
    [agents, localPinnedAgents, persistPins]
  );

  return (
    <AgentsContext.Provider
      value={{
        agents,
        pinnedAgents: localPinnedAgents,
        pinnedAgentIds: localPinnedAgents.map((agent) => agent.id),
        isLoading: isLoadingAgents,
        currentAgent,
        currentAgentId: currentAgent?.id ?? null,
        refreshAgents,
        refreshPinnedAgents: refreshUser,
        togglePinnedAgent,
        updatePinnedAgents,
      }}
    >
      {children}
    </AgentsContext.Provider>
  );
}

export function useAgentsContext() {
  const ctx = useContext(AgentsContext);
  if (!ctx) {
    throw new Error("useAgentsContext must be used within an AgentsProvider");
  }
  return ctx;
}
