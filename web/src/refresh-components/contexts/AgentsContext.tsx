"use client";

import React, {
  createContext,
  useState,
  useContext,
  useMemo,
  useEffect,
  useRef,
  Dispatch,
  SetStateAction,
} from "react";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { useSearchParams } from "next/navigation";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import {
  UserSpecificAssistantPreference,
  UserSpecificAssistantPreferences,
} from "@/lib/types";
import { useAssistantPreferences } from "@/app/chat/hooks/useAssistantPreferences";

async function fetchAllAgents(): Promise<MinimalPersonaSnapshot[]> {
  try {
    const response = await fetch("/api/persona", {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
      },
    });
    if (!response.ok) throw new Error("Failed to fetch agents");
    const agents: MinimalPersonaSnapshot[] = await response.json();
    return agents;
  } catch (error) {
    console.error("Error fetching agents:", error);
    return [];
  }
}

async function pinAgents(pinnedAgentIds: number[]) {
  console.log(pinnedAgentIds);
  const response = await fetch(`/api/user/pinned-assistants`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      ordered_assistant_ids: pinnedAgentIds,
    }),
  });
  if (!response.ok) {
    throw new Error("Failed to update pinned assistants");
  }
}

function getPinnedAgents(
  agents: MinimalPersonaSnapshot[],
  pinnedAgentIds?: number[]
): MinimalPersonaSnapshot[] {
  return pinnedAgentIds
    ? (pinnedAgentIds
        .map((pinnedAgentId) =>
          agents.find((agent) => agent.id === pinnedAgentId)
        )
        .filter((agent) => !!agent) as MinimalPersonaSnapshot[])
    : agents.filter((agent) => agent.is_default_persona && agent.id !== 0);
}

interface AgentsProviderProps {
  agents: MinimalPersonaSnapshot[];
  pinnedAgentIds: number[];
  children: React.ReactNode;
}

export function AgentsProvider({
  agents: initialAgents,
  pinnedAgentIds: initialPinnedAgentIds,
  children,
}: AgentsProviderProps) {
  const [agents, setAgents] = useState<MinimalPersonaSnapshot[]>(initialAgents);
  const [pinnedAgents, setPinnedAgents] = useState<MinimalPersonaSnapshot[]>(
    () => getPinnedAgents(agents, initialPinnedAgentIds)
  );

  const { assistantPreferences, setSpecificAssistantPreferences } =
    useAssistantPreferences();
  const [forcedToolIds, setForcedToolIds] = useState<number[]>([]);

  const isInitialMount = useRef(true);
  const searchParams = useSearchParams();
  const currentAgentIdRaw = searchParams?.get(SEARCH_PARAM_NAMES.PERSONA_ID);
  const currentAgentId = currentAgentIdRaw ? parseInt(currentAgentIdRaw) : null;
  const currentAgent = useMemo(
    () =>
      currentAgentId
        ? agents.find((agent) => agent.id === currentAgentId) || null
        : null,
    [agents, currentAgentId]
  );

  async function refreshAgents() {
    setAgents(await fetchAllAgents());
  }

  function togglePinnedAgent(
    agent: MinimalPersonaSnapshot,
    shouldPin: boolean
  ) {
    setPinnedAgents((prev) =>
      shouldPin
        ? [...prev, agent]
        : prev.filter((prevAgent) => prevAgent.id !== agent.id)
    );
  }

  useEffect(() => {
    if (isInitialMount.current) {
      isInitialMount.current = false;
      return;
    }

    pinAgents(pinnedAgents.map((agent) => agent.id));
  }, [pinnedAgents]);

  return (
    <AgentsContext.Provider
      value={{
        agents,
        refreshAgents,
        pinnedAgents,
        setPinnedAgents,
        togglePinnedAgent,
        currentAgent,
        agentPreferences: assistantPreferences,
        setSpecificAgentPreferences: setSpecificAssistantPreferences,
        forcedToolIds,
        setForcedToolIds,
      }}
    >
      {children}
    </AgentsContext.Provider>
  );
}

interface AgentsContextType {
  // All available agents
  agents: MinimalPersonaSnapshot[];
  refreshAgents: () => Promise<void>;

  // Pinned agents (from user preferences)
  pinnedAgents: MinimalPersonaSnapshot[];
  setPinnedAgents: Dispatch<SetStateAction<MinimalPersonaSnapshot[]>>;
  togglePinnedAgent: (agent: MinimalPersonaSnapshot, request: boolean) => void;

  // Currently live/active agent (from searchParams)
  currentAgent: MinimalPersonaSnapshot | null;

  agentPreferences: UserSpecificAssistantPreferences | null;
  setSpecificAgentPreferences: (
    assistantId: number,
    assistantPreferences: UserSpecificAssistantPreference
  ) => void;

  forcedToolIds: number[];
  setForcedToolIds: Dispatch<SetStateAction<number[]>>;
}

const AgentsContext = createContext<AgentsContextType | undefined>(undefined);

export function useAgentsContext(): AgentsContextType {
  const context = useContext(AgentsContext);
  if (!context)
    throw new Error("useAgentsContext must be used within an AgentsProvider");
  return context;
}
