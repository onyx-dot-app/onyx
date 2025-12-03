import useSWR from "swr";
import { ChatSession } from "@/app/chat/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";

interface ChatSessionsResponse {
  sessions: ChatSession[];
}

export function useChatSessions() {
  const { data, error, mutate } = useSWR<ChatSessionsResponse>(
    "/api/chat/get-user-chat-sessions",
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 30000,
    }
  );

  return {
    chatSessions: data?.sessions ?? [],
    isLoading: !error && !data,
    error,
    refreshChatSessions: mutate,
  };
}
