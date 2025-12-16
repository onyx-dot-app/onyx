"use client";

import useSWR, { KeyedMutator } from "swr";
import { ChatSession } from "@/app/chat/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useSearchParams } from "next/navigation";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";

interface ChatSessionsResponse {
  sessions: ChatSession[];
}

interface UseChatSessionsOutput {
  chatSessions: ChatSession[];
  currentChatSessionId: string | null;
  currentChatSession: ChatSession | null;
  isLoading: boolean;
  error: any;
  refreshChatSessions: KeyedMutator<ChatSessionsResponse>;
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

  const chatSessions = data?.sessions ?? [];
  const searchParams = useSearchParams();
  const currentChatSessionId = searchParams.get(SEARCH_PARAM_NAMES.CHAT_ID);
  const currentChatSession =
    chatSessions.find(
      (chatSession) => chatSession.id === currentChatSessionId
    ) ?? null;

  return {
    chatSessions,
    currentChatSessionId,
    currentChatSession,

    isLoading: !error && !data,
    error,
    refreshChatSessions: mutate,
  };
}
