"use client";

/**
 * ChatSessionContext
 *
 * Provides chat session data plus helpers derived from the URL and assistant list.
 *
 * Interface:
 * - `chatSessions`: ChatSession[] — all sessions from `/api/chat/get-user-chat-sessions`.
 * - `currentChatSessionId`: string | null — `chatId` from the URL (SEARCH_PARAM_NAMES.CHAT_ID).
 * - `currentChatSession`: ChatSession | null — session matching `currentChatSessionId`, or null.
 * - `agentForChatSession`: MinimalPersonaSnapshot | null — agent for `currentChatSession` via `persona_id`; null if none.
 * - `isLoading`: boolean — true while sessions are loading.
 * - `error`: unknown — SWR error value.
 * - `refreshChatSessions()`: KeyedMutator<ChatSessionsResponse> — SWR mutate for sessions.
 */

import { createContext, useContext, useMemo, type ReactNode } from "react";
import useSWR, { KeyedMutator } from "swr";
import { useSearchParams } from "next/navigation";
import { ChatSession } from "@/app/chat/interfaces";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import { useAgentsContext } from "@/contexts/AgentsContext";

interface ChatSessionsResponse {
  sessions: ChatSession[];
}

interface ChatSessionContextValue {
  chatSessions: ChatSession[];
  currentChatSessionId: string | null;
  currentChatSession: ChatSession | null;
  agentForCurrentChatSession: MinimalPersonaSnapshot | null;
  isLoading: boolean;
  error: unknown;
  refreshChatSessions: KeyedMutator<ChatSessionsResponse>;
}

const ChatSessionContext = createContext<ChatSessionContextValue | undefined>(
  undefined
);

export function ChatSessionProvider({ children }: { children: ReactNode }) {
  const { data, error, mutate } = useSWR<ChatSessionsResponse>(
    "/api/chat/get-user-chat-sessions",
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 30000,
    }
  );

  const chatSessions = data?.sessions ?? [];
  const searchParams = useSearchParams();
  const currentChatSessionId = searchParams.get(SEARCH_PARAM_NAMES.CHAT_ID);
  const currentChatSession =
    chatSessions.find(
      (chatSession) => chatSession.id === currentChatSessionId
    ) ?? null;

  const { agents } = useAgentsContext();

  const agentForCurrentChatSession = useMemo(() => {
    if (!currentChatSession) return null;
    return (
      agents.find((agent) => agent.id === currentChatSession.persona_id) ?? null
    );
  }, [agents, currentChatSession]);

  const value: ChatSessionContextValue = {
    chatSessions,
    currentChatSessionId,
    currentChatSession,
    agentForCurrentChatSession,
    isLoading: !error && !data,
    error,
    refreshChatSessions: mutate,
  };

  return (
    <ChatSessionContext.Provider value={value}>
      {children}
    </ChatSessionContext.Provider>
  );
}

export function useChatSessionContext() {
  const ctx = useContext(ChatSessionContext);
  if (!ctx) {
    throw new Error(
      "useChatSessionContext must be used within a ChatSessionProvider"
    );
  }
  return ctx;
}
