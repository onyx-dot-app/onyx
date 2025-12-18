"use client";

/**
 * ChatSessionContext
 *
 * Provides chat session data plus helpers derived from the URL and assistant list.
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
  /** All sessions from `/api/chat/get-user-chat-sessions`. */
  chatSessions: ChatSession[];

  /** `chatId` from the URL (SEARCH_PARAM_NAMES.CHAT_ID). */
  currentChatSessionId: string | null;

  /** Session matching `currentChatSessionId`, or null. */
  currentChatSession: ChatSession | null;

  /** Agent for `currentChatSession` via `persona_id`; null if none.
   *
   * This is different than the `currentAgent` provided by the `AgentsContext` because this agent is pulled from the *chat-session*.
   * The `currentAgent` provided by `AgentsContext` is from the URL.
   */
  agentForCurrentChatSession: MinimalPersonaSnapshot | null;

  /** True while sessions are loading. */
  isLoading: boolean;

  /** SWR error value, if any. */
  error: unknown;

  /** SWR mutate for sessions. */
  refreshChatSessions: KeyedMutator<ChatSessionsResponse>;
}

const ChatSessionContext = createContext<ChatSessionContextValue | undefined>(
  undefined
);

interface ChatSessionProviderProps {
  children: ReactNode;
}

export function ChatSessionProvider({ children }: ChatSessionProviderProps) {
  const { data, isLoading, error, mutate } = useSWR<ChatSessionsResponse>(
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

  const currentChatSession = useMemo(
    () =>
      chatSessions.find(
        (chatSession) => chatSession.id === currentChatSessionId
      ) ?? null,
    [chatSessions, currentChatSessionId]
  );

  const { agents } = useAgentsContext();

  const agentForCurrentChatSession = useMemo(() => {
    if (!currentChatSession) return null;
    return (
      agents.find((agent) => agent.id === currentChatSession.persona_id) ?? null
    );
  }, [agents, currentChatSession]);

  return (
    <ChatSessionContext.Provider
      value={{
        chatSessions,
        currentChatSessionId,
        currentChatSession,
        agentForCurrentChatSession,
        isLoading,
        error,
        refreshChatSessions: mutate,
      }}
    >
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
