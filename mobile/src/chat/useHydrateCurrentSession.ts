// Loads + hydrates the message tree for the CURRENT session when it's a real
// backend session that hasn't been loaded yet (e.g. opened from Recents). This is
// what lets one chat screen render any session instead of a separate [sessionId]
// route. Web parity: GET /chat/get-chat-session/{id} → processRawChatHistory → store.
//
// We deliberately SKIP sessions that already hold a local tree — a draft, a
// just-created/streaming session (optimistic messages), or a persisted-with-tree
// session — so loading never clobbers in-flight or cached state.
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";

import { errorHandlingFetcher, SWR_KEYS } from "@/lib/api";
import { clientConfig } from "@/query/client";
import type { BackendChatSession } from "@/lib/types";
import { useChatSessionStore } from "@/state/chatSessionStore";
import { processRawChatHistory } from "@/state/processRawChatHistory";
import { isUuid } from "./uuid";

export interface HydrateCurrentSessionResult {
  /** True while the current session's history is being fetched. */
  isLoading: boolean;
  /** True if the fetch failed. */
  isError: boolean;
  /** Re-run the fetch (for an error-state "Try again" affordance). */
  retry: () => void;
}

export function useHydrateCurrentSession(): HydrateCurrentSessionResult {
  const currentSessionId = useChatSessionStore((s) => s.currentSessionId);
  const session = useChatSessionStore((s) =>
    currentSessionId ? s.sessions.get(currentSessionId) : undefined,
  );

  const isRealSession =
    !!currentSessionId && isUuid(currentSessionId);
  // Load only when there is no local tree yet (opened from Recents / cold).
  const needsLoad =
    isRealSession &&
    (!session || (!session.isLoaded && session.messageTree.size === 0));

  const query = useQuery({
    queryKey: ["getChatSession", currentSessionId],
    queryFn: () =>
      errorHandlingFetcher<BackendChatSession>(
        SWR_KEYS.getChatSession(currentSessionId as string),
        clientConfig,
      ),
    enabled: needsLoad,
  });

  useEffect(() => {
    if (!query.data || !currentSessionId) return;
    const store = useChatSessionStore.getState();
    // Gate the WRITE with the same invariant as the fetch: never clobber a session
    // that already holds a local tree. React Query keeps `query.data` cached (and
    // returns it even when the query is disabled), so without this guard a
    // B→A→B re-entry would re-apply stale history over messages the user has since
    // sent/streamed in B. Only hydrate a still-empty, not-yet-loaded session.
    const existing = store.sessions.get(currentSessionId);
    if (existing && (existing.isLoaded || existing.messageTree.size > 0)) return;
    // initializeSession marks isLoaded=true; updateSessionAndMessageTree installs
    // the hydrated tree (and makes the session current).
    store.initializeSession(currentSessionId, query.data);
    const tree = processRawChatHistory(
      query.data.messages,
      query.data.packets,
    );
    store.updateSessionAndMessageTree(currentSessionId, tree);
  }, [query.data, currentSessionId]);

  return {
    isLoading: needsLoad && !query.isError,
    isError: needsLoad && query.isError,
    retry: () => {
      void query.refetch();
    },
  };
}
