import { useMemo } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";

import { apiFetch } from "@/api/client";
import { QUERY_KEYS } from "@/api/query-keys";
import { useSession } from "@/state/session";

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
      // `before` is exclusive (backend: time_updated < before); a same-microsecond
      // tie straddling a page boundary can drop a session. Matches web's cursor; a
      // real fix needs a backend (time_updated, id) compound cursor — deferred to PR 4.
      return lastPage.sessions[lastPage.sessions.length - 1]!.time_updated;
    },
  });

  const sessions = useMemo(
    () => query.data?.pages.flatMap((page) => page.sessions) ?? [],
    [query.data],
  );

  return { ...query, sessions };
}
