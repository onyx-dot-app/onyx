// Hydrates the CURRENT session's tree when it's a real backend session not yet
// loaded (e.g. opened from Recents). Mirrors web GET /chat/get-chat-session/{id}.
// Skips sessions that already hold a local tree so loading never clobbers in-flight
// or cached state.
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";

import { errorHandlingFetcher, SWR_KEYS } from "@/lib/api";
import { clientConfig } from "@/query/client";
import type { BackendChatSession } from "@/lib/types";
import { useChatSessionStore } from "@/state/chatSessionStore";
import { processRawChatHistory } from "@/state/processRawChatHistory";
import { isUuid } from "./uuid";

export interface HydrateCurrentSessionResult {
  isLoading: boolean;
  isError: boolean;
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
    // Gate the write with the same invariant as the fetch: React Query keeps
    // `query.data` cached even when disabled, so without this a B→A→B re-entry would
    // re-apply stale history over messages the user has since sent in B.
    const existing = store.sessions.get(currentSessionId);
    if (existing && (existing.isLoaded || existing.messageTree.size > 0)) return;
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
