"use client";

/**
 * AgentsContext
 *
 * Provides agent data plus pinning helpers for components that need to read or
 * mutate assistant ordering without prop-drilling.
 *
 * This context should be provided at the app-level (it transcends chat-sessions, namely).
 *
 * Interface:
 * - `agents`: MinimalPersonaSnapshot[] — all assistants from `/api/persona`; use for lookups and listings.
 * - `pinnedAgents`: MinimalPersonaSnapshot[] — assistants currently pinned, in display order (optimistic).
 * - `pinnedAgentIds`: number[] — ids of `pinnedAgents` for lightweight checks.
 * - `isLoading`: boolean — true while the initial agents list is still loading.
 * - `togglePinnedAgent(agentId, shouldPin)`: Promise<void> — pin/unpin an agent with optimistic UI updates; persists via `pinAgents`.
 * - `updatePinnedAgents(agentIds)`: Promise<void> — replace/reorder the entire pinned list (e.g., drag-and-drop); persists and updates local state.
 * - `refreshAgents()`: Promise<MinimalPersonaSnapshot[] | undefined> — SWR mutate for the agents list; call after server-side changes to assistants.
 * - `refreshPinnedAgents()`: Promise<void> — refreshes user data to re-pull pinned ids from `/me` (used after pin/unpin elsewhere).
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

interface AgentsContextValue {
  agents: MinimalPersonaSnapshot[];
  pinnedAgents: MinimalPersonaSnapshot[];
  pinnedAgentIds: number[];
  isLoading: boolean;
  refreshAgents: () => Promise<MinimalPersonaSnapshot[] | undefined>;
  refreshPinnedAgents: () => Promise<void>;
  togglePinnedAgent: (agentId: number, shouldPin: boolean) => Promise<void>;
  updatePinnedAgents: (agentIds: number[]) => Promise<void>;
}

const AgentsContext = createContext<AgentsContextValue | undefined>(undefined);

export function AgentsProvider({ children }: { children: ReactNode }) {
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

      setLocalPinnedAgents(nextPinned);
      await persistPins(nextPinned.map((a) => a.id));
    },
    [agents, localPinnedAgents, persistPins]
  );

  const updatePinnedAgents = useCallback(
    async (agentIds: number[]) => {
      const nextPinned = agentIds
        .map((id) => agents.find((agent) => agent.id === id))
        .filter((agent): agent is MinimalPersonaSnapshot => !!agent);

      setLocalPinnedAgents(nextPinned);
      await persistPins(nextPinned.map((a) => a.id));
    },
    [agents, persistPins]
  );

  return (
    <AgentsContext.Provider
      value={{
        agents,
        pinnedAgents: localPinnedAgents,
        pinnedAgentIds: localPinnedAgents.map((agent) => agent.id),
        isLoading: isLoadingAgents,
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
