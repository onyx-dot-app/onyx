import { useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { useAgents } from "./useAgents";
import { useSession } from "@/app/chat/stores/useChatSessionStore";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";

/**
 * Hook to determine the currently active agent based on:
 * 1. URL param `assistantId`
 * 2. Chat session's `persona_id`
 * 3. Falls back to null if neither is present
 */
export function useCurrentAgent(): {
  currentAgent: MinimalPersonaSnapshot | null;
  isLoading: boolean;
} {
  const { agents, isLoading } = useAgents();
  const searchParams = useSearchParams();

  const chatId = searchParams?.get(SEARCH_PARAM_NAMES.CHAT_ID);
  const assistantIdParam = searchParams?.get(SEARCH_PARAM_NAMES.PERSONA_ID);

  // Get session from Zustand store
  const chatSession = useSession(chatId || "");

  const currentAgent = useMemo(() => {
    if (agents.length === 0) return null;

    // Priority: URL param > chat session persona > null
    const agentId = assistantIdParam
      ? parseInt(assistantIdParam)
      : chatSession?.personaId;

    if (agentId) {
      return agents.find((a) => a.id === agentId) ?? null;
    }

    return null;
  }, [agents, assistantIdParam, chatSession?.personaId]);

  return {
    currentAgent,
    isLoading,
  };
}
