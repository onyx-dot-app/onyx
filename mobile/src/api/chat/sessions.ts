import { useMemo } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";

import { apiFetch } from "@/api/client";
import { QUERY_KEYS } from "@/api/query-keys";
import { useSession } from "@/state/session";
import { DEFAULT_AGENT_ID } from "@/chat/agents";
import { BackendChatSession } from "@/chat/interfaces";

// Pre-creates a session so the first message sends with a real chat_session_id.
export async function createChatSession(
  personaId: number = DEFAULT_AGENT_ID,
  projectId: number | null = null,
): Promise<string> {
  const { chat_session_id } = await apiFetch<{ chat_session_id: string }>(
    "/chat/create-chat-session",
    {
      method: "POST",
      body: { persona_id: personaId, description: null, project_id: projectId },
    },
  );
  return chat_session_id;
}

// Session snapshot for hydration.
export async function getChatSession(
  sessionId: string,
): Promise<BackendChatSession> {
  return apiFetch<BackendChatSession>(`/chat/get-chat-session/${sessionId}`);
}

// client abort alone leaves the backend generating
export async function stopChatSession(sessionId: string): Promise<void> {
  await apiFetch<void>(`/chat/stop-chat-session/${sessionId}`, {
    method: "POST",
  });
}

// `name: null` makes the backend LLM-generate a title from the session's history.
export async function renameChatSession(sessionId: string): Promise<void> {
  await apiFetch<{ new_name: string | null }>("/chat/rename-chat-session", {
    method: "PUT",
    body: { chat_session_id: sessionId, name: null },
  });
}

export type ChatSessionSharedStatus = "private" | "public";

// Mirrors backend `ChatSessionDetails` (get-user-chat-sessions); `name` can be
// null → the UI shows "New Chat".
export interface ChatSessionSummary {
  id: string;
  name: string | null;
  persona_id: number | null;
  time_created: string;
  time_updated: string;
  shared_status: ChatSessionSharedStatus;
  current_alternate_model: string | null;
  current_temperature_override: number | null;
}

interface ChatSessionsPage {
  sessions: ChatSessionSummary[];
  has_more: boolean;
}

const PAGE_SIZE = 50;

// Mirrors web's `useChatSessions`. Backend returns newest-first (time_updated
// DESC), so page 1 is the most recent chats; the `before` cursor (last loaded
// session's time_updated) walks into older pages. Project chats excluded (PR 6).
export function useChatSessions() {
  const serverUrl = useSession((state) => state.serverUrl);

  const query = useInfiniteQuery({
    queryKey: QUERY_KEYS.chatSessions(serverUrl),
    // No serverUrl → `getBaseUrl()` throws, so stay idle until connected.
    enabled: serverUrl !== null,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => {
      const params = new URLSearchParams({
        page_size: String(PAGE_SIZE),
        only_non_project_chats: "true",
      });
      if (pageParam) params.set("before", pageParam);
      return apiFetch<ChatSessionsPage>(
        `/chat/get-user-chat-sessions?${params.toString()}`,
        { signal },
      );
    },
    getNextPageParam: (lastPage) => {
      if (!lastPage.has_more || lastPage.sessions.length === 0)
        return undefined;
      // `before` is exclusive, so a same-timestamp tie across a page boundary can drop a session.
      // Matches web; the compound-cursor fix stays out of scope to keep the port backend-free.
      return lastPage.sessions[lastPage.sessions.length - 1]!.time_updated;
    },
  });

  const sessions = useMemo(
    () => query.data?.pages.flatMap((page) => page.sessions) ?? [],
    [query.data],
  );

  return { ...query, sessions };
}
