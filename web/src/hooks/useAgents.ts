"use client";

import { useMemo } from "react";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { useSearchParams } from "next/navigation";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import useChatSessions from "./useChatSessions";
import { useAgentsContext } from "@/contexts/AgentsContext";

/**
 * Hook to determine the currently active agent based on:
 * 1. URL param `assistantId`
 * 2. Chat session's `persona_id`
 * 3. Falls back to null if neither is present
 */
export function useCurrentAgent(): MinimalPersonaSnapshot | null {
  const { agents } = useAgentsContext();
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
