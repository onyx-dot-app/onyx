"use client";

import useSWR, { KeyedMutator } from "swr";
import { ChatSession } from "@/app/chat/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import useAppFocus from "./useAppFocus";
import { useAgents } from "./useAgents";
import { DEFAULT_ASSISTANT_ID } from "@/lib/constants";

interface ChatSessionsResponse {
  sessions: ChatSession[];
}

interface UseChatSessionsOutput {
  chatSessions: ChatSession[];
  currentChatSessionId: string | null;
  currentChatSession: ChatSession | null;
  agentForCurrentChatSession: MinimalPersonaSnapshot | null;
  isLoading: boolean;
  error: any;
  refreshChatSessions: KeyedMutator<ChatSessionsResponse>;
}

function useFindAgentForCurrentChatSession(
  currentChatSession: ChatSession | null
): MinimalPersonaSnapshot | null {
  const { agents } = useAgents();
  const appFocus = useAppFocus();

  let agentIdToFind: number;

  // This could be an alreaady existing chat session.
  if (currentChatSession) {
    agentIdToFind = currentChatSession.persona_id;
  }

  // This could be a new chat-session. Therefore, `currentChatSession` is false, but there could still be some agent.
  else if (appFocus.isNewSession()) {
    agentIdToFind = DEFAULT_ASSISTANT_ID;
  }

  // Or this could be a new chat-session with an agent.
  else if (appFocus.isAgent()) {
    agentIdToFind = Number.parseInt(appFocus.getId()!);
  }

  return agents.find((agent) => agent.id === agentIdToFind) ?? null;
}

export default function useChatSessions(): UseChatSessionsOutput {
  const { data, error, mutate } = useSWR<ChatSessionsResponse>(
    "/api/chat/get-user-chat-sessions",
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 30000,
    }
  );

  const appFocus = useAppFocus();

  const chatSessions = data?.sessions ?? [];
  const currentChatSessionId = appFocus.isChat() ? appFocus.getId() : null;
  const currentChatSession =
    chatSessions.find(
      (chatSession) => chatSession.id === currentChatSessionId
    ) ?? null;

  const agentForCurrentChatSession =
    useFindAgentForCurrentChatSession(currentChatSession);

  return {
    chatSessions,
    currentChatSessionId,
    currentChatSession,
    agentForCurrentChatSession,
    isLoading: !error && !data,
    error,
    refreshChatSessions: mutate,
  };
}
