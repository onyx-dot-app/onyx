"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
} from "react";
import useSWRInfinite from "swr/infinite";
import { ChatSession, ChatSessionSharedStatus } from "@/app/app/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import useAppFocus from "./useAppFocus";
import { useAgents } from "./useAgents";
import { DEFAULT_ASSISTANT_ID } from "@/lib/constants";

const PAGE_SIZE = 50;
const MIN_LOADING_DURATION_MS = 300;

interface ChatSessionsResponse {
  sessions: ChatSession[];
  has_more: boolean;
}

export interface PendingChatSessionParams {
  chatSessionId: string;
  personaId: number;
  projectId?: number | null;
}

interface UseChatSessionsOutput {
  chatSessions: ChatSession[];
  currentChatSessionId: string | null;
  currentChatSession: ChatSession | null;
  agentForCurrentChatSession: MinimalPersonaSnapshot | null;
  isLoading: boolean;
  error: any;
  refreshChatSessions: () => Promise<ChatSessionsResponse[] | undefined>;
  addPendingChatSession: (params: PendingChatSessionParams) => void;
  removeSession: (sessionId: string) => void;
  hasMore: boolean;
  isLoadingMore: boolean;
  loadMore: () => void;
}

// ---------------------------------------------------------------------------
// Shared module-level store for pending chat sessions
// ---------------------------------------------------------------------------
// Pending sessions are optimistic new sessions shown in the sidebar before
// the server returns them. This must be module-level so all hook instances
// (sidebar, ChatButton, etc.) share the same state.

const pendingSessionsStore = {
  sessions: new Map<string, ChatSession>(),
  listeners: new Set<() => void>(),
  cachedSnapshot: [] as ChatSession[],

  add(session: ChatSession) {
    this.sessions.set(session.id, session);
    this.updateSnapshot();
    this.notify();
  },

  remove(sessionId: string) {
    if (this.sessions.delete(sessionId)) {
      this.updateSnapshot();
      this.notify();
    }
  },

  has(sessionId: string): boolean {
    return this.sessions.has(sessionId);
  },

  subscribe(listener: () => void) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  },

  notify() {
    this.listeners.forEach((listener) => listener());
  },

  updateSnapshot() {
    this.cachedSnapshot = Array.from(this.sessions.values());
  },

  getSnapshot(): ChatSession[] {
    return this.cachedSnapshot;
  },
};

// Stable empty array for SSR
const EMPTY_SESSIONS: ChatSession[] = [];

function usePendingSessions(): ChatSession[] {
  return useSyncExternalStore(
    (callback) => pendingSessionsStore.subscribe(callback),
    () => pendingSessionsStore.getSnapshot(),
    () => EMPTY_SESSIONS
  );
}

// ---------------------------------------------------------------------------
// Helper hooks
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Main hook
// ---------------------------------------------------------------------------

export default function useChatSessions(): UseChatSessionsOutput {
  const getKey = (
    pageIndex: number,
    previousPageData: ChatSessionsResponse | null
  ): string | null => {
    // No more pages
    if (previousPageData && !previousPageData.has_more) return null;

    // First page — no cursor
    if (pageIndex === 0) {
      return `/api/chat/get-user-chat-sessions?page_size=${PAGE_SIZE}`;
    }

    // Subsequent pages — cursor from the last session of the previous page
    const lastSession =
      previousPageData!.sessions[previousPageData!.sessions.length - 1];
    if (!lastSession) return null;

    const params = new URLSearchParams({
      page_size: PAGE_SIZE.toString(),
      before: lastSession.time_updated,
    });
    return `/api/chat/get-user-chat-sessions?${params.toString()}`;
  };

  const { data, error, size, setSize, mutate, isValidating } =
    useSWRInfinite<ChatSessionsResponse>(getKey, errorHandlingFetcher, {
      revalidateOnFocus: false,
      revalidateFirstPage: true,
      revalidateAll: false,
      dedupingInterval: 30000,
    });

  const appFocus = useAppFocus();
  const pendingSessions = usePendingSessions();

  // Flatten all pages into a single session list
  const allFetchedSessions = useMemo(
    () => (data ? data.flatMap((page) => page.sessions) : []),
    [data]
  );

  // hasMore: check the last loaded page
  const hasMore = useMemo(() => {
    if (!data || data.length === 0) return false;
    const lastPage = data[data.length - 1];
    return lastPage ? lastPage.has_more : false;
  }, [data]);

  const [isLoadingMore, setIsLoadingMore] = useState(false);

  const loadMore = useCallback(async () => {
    if (isLoadingMore || !hasMore) return;

    setIsLoadingMore(true);
    const loadStart = Date.now();

    try {
      await setSize((s) => s + 1);

      // Enforce minimum loading duration to avoid skeleton flash
      const elapsed = Date.now() - loadStart;
      if (elapsed < MIN_LOADING_DURATION_MS) {
        await new Promise((r) =>
          setTimeout(r, MIN_LOADING_DURATION_MS - elapsed)
        );
      }
    } catch (err) {
      console.error("Failed to load more chat sessions:", err);
    } finally {
      setIsLoadingMore(false);
    }
  }, [isLoadingMore, hasMore, setSize]);

  // Clean up pending sessions that now appear in fetched data
  useEffect(() => {
    const fetchedIds = new Set(allFetchedSessions.map((s) => s.id));
    pendingSessions.forEach((pending) => {
      if (fetchedIds.has(pending.id)) {
        pendingSessionsStore.remove(pending.id);
      }
    });
  }, [allFetchedSessions, pendingSessions]);

  // Merge fetched sessions + pending sessions.
  // Dedup: pending sessions that already appear in fetched data are excluded.
  const chatSessions = useMemo(() => {
    const fetchedIds = new Set(allFetchedSessions.map((s) => s.id));
    const remainingPending = pendingSessions.filter(
      (pending) => !fetchedIds.has(pending.id)
    );
    return [...remainingPending, ...allFetchedSessions];
  }, [allFetchedSessions, pendingSessions]);

  const currentChatSessionId = appFocus.isChat() ? appFocus.getId() : null;
  const currentChatSession =
    chatSessions.find(
      (chatSession) => chatSession.id === currentChatSessionId
    ) ?? null;

  const agentForCurrentChatSession =
    useFindAgentForCurrentChatSession(currentChatSession);

  const addPendingChatSession = useCallback(
    ({ chatSessionId, personaId, projectId }: PendingChatSessionParams) => {
      if (projectId != null) return;
      if (pendingSessionsStore.has(chatSessionId)) return;

      const now = new Date().toISOString();
      pendingSessionsStore.add({
        id: chatSessionId,
        name: "",
        persona_id: personaId,
        time_created: now,
        time_updated: now,
        shared_status: ChatSessionSharedStatus.Private,
        project_id: projectId ?? null,
        current_alternate_model: "",
        current_temperature_override: null,
      });
    },
    []
  );

  const removeSession = useCallback(
    (sessionId: string) => {
      pendingSessionsStore.remove(sessionId);
      // Optimistically remove from all loaded pages
      mutate(
        (pages) =>
          pages?.map((page) => ({
            ...page,
            sessions: page.sessions.filter((s) => s.id !== sessionId),
          })),
        { revalidate: false }
      );
    },
    [mutate]
  );

  const refreshChatSessions = useCallback(() => mutate(), [mutate]);

  return {
    chatSessions,
    currentChatSessionId,
    currentChatSession,
    agentForCurrentChatSession,
    isLoading: !error && !data,
    error,
    refreshChatSessions,
    addPendingChatSession,
    removeSession,
    hasMore,
    isLoadingMore,
    loadMore,
  };
}
