"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
} from "react";
import useSWR, { KeyedMutator } from "swr";
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
  refreshChatSessions: KeyedMutator<ChatSessionsResponse>;
  addPendingChatSession: (params: PendingChatSessionParams) => void;
  removeSession: (sessionId: string) => void;
  clearAdditionalSessions: () => void;
  hasMore: boolean;
  isLoadingMore: boolean;
  loadMore: () => void;
}

// ---------------------------------------------------------------------------
// Shared module-level stores
// ---------------------------------------------------------------------------
// These persist across SWR revalidations and are shared across all hook
// instances so that any component can trigger mutations (add/remove/clear)
// and every component sees the result immediately.

// Store for pending chat sessions (optimistic new sessions not yet returned
// by the server).
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

// Store for additional sessions loaded via infinite scroll (pages 2+).
// Also tracks `hasMore` so the pagination state is shared.
const additionalSessionsStore = {
  sessions: [] as ChatSession[],
  hasMore: false,
  listeners: new Set<() => void>(),
  cachedSnapshot: [] as ChatSession[],

  append(newSessions: ChatSession[]) {
    this.sessions = [...this.sessions, ...newSessions];
    this.cachedSnapshot = this.sessions;
    this.notify();
  },

  remove(sessionId: string) {
    const len = this.sessions.length;
    this.sessions = this.sessions.filter((s) => s.id !== sessionId);
    if (this.sessions.length !== len) {
      this.cachedSnapshot = this.sessions;
      this.notify();
    }
  },

  clear() {
    if (this.sessions.length > 0 || this.hasMore) {
      this.sessions = [];
      this.hasMore = false;
      this.cachedSnapshot = [];
      this.notify();
    }
  },

  setHasMore(value: boolean) {
    if (this.hasMore !== value) {
      this.hasMore = value;
      this.notify();
    }
  },

  subscribe(listener: () => void) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  },

  notify() {
    this.listeners.forEach((listener) => listener());
  },

  getSnapshot(): ChatSession[] {
    return this.cachedSnapshot;
  },
};

// Stable empty array for SSR - must be defined outside component to avoid infinite loop
const EMPTY_SESSIONS: ChatSession[] = [];

function usePendingSessions(): ChatSession[] {
  return useSyncExternalStore(
    (callback) => pendingSessionsStore.subscribe(callback),
    () => pendingSessionsStore.getSnapshot(),
    () => EMPTY_SESSIONS
  );
}

function useAdditionalSessions(): ChatSession[] {
  return useSyncExternalStore(
    (callback) => additionalSessionsStore.subscribe(callback),
    () => additionalSessionsStore.getSnapshot(),
    () => EMPTY_SESSIONS
  );
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
    `/api/chat/get-user-chat-sessions?page_size=${PAGE_SIZE}`,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 30000,
    }
  );

  const appFocus = useAppFocus();
  const pendingSessions = usePendingSessions();
  const additionalSessions = useAdditionalSessions();
  const fetchedSessions = data?.sessions ?? [];

  const [isLoadingMore, setIsLoadingMore] = useState(false);

  // Sync hasMore from the initial SWR response when no additional pages loaded yet
  useEffect(() => {
    if (data && additionalSessions.length === 0) {
      additionalSessionsStore.setHasMore(data.has_more);
    }
  }, [data, additionalSessions.length]);

  const hasMore = additionalSessionsStore.hasMore;

  const loadMore = useCallback(async () => {
    if (isLoadingMore || !additionalSessionsStore.hasMore) return;

    const allSessions = [...fetchedSessions, ...additionalSessions];
    const lastSession = allSessions[allSessions.length - 1];
    if (!lastSession) return;

    setIsLoadingMore(true);
    const loadStart = Date.now();

    try {
      const params = new URLSearchParams({
        page_size: PAGE_SIZE.toString(),
        before: lastSession.time_updated,
      });
      const response: ChatSessionsResponse = await errorHandlingFetcher(
        `/api/chat/get-user-chat-sessions?${params.toString()}`
      );

      // Enforce minimum loading duration to avoid skeleton flash
      const elapsed = Date.now() - loadStart;
      if (elapsed < MIN_LOADING_DURATION_MS) {
        await new Promise((r) =>
          setTimeout(r, MIN_LOADING_DURATION_MS - elapsed)
        );
      }

      additionalSessionsStore.append(response.sessions);
      additionalSessionsStore.setHasMore(response.has_more);
    } catch (err) {
      console.error("Failed to load more chat sessions:", err);
    } finally {
      setIsLoadingMore(false);
    }
  }, [fetchedSessions, additionalSessions, isLoadingMore]);

  // Clean up pending sessions that now appear in fetched data
  // (they now have messages and the server returns them)
  useEffect(() => {
    const fetchedIds = new Set(fetchedSessions.map((s) => s.id));
    pendingSessions.forEach((pending) => {
      if (fetchedIds.has(pending.id)) {
        pendingSessionsStore.remove(pending.id);
      }
    });
  }, [fetchedSessions, pendingSessions]);

  // Merge fetched sessions (first page) + additional pages + pending sessions.
  // Deduplicates: if a chat moved into the first page (e.g. it was updated),
  // remove it from additionalSessions so it doesn't appear twice.
  const chatSessions = useMemo(() => {
    const firstPageIds = new Set(fetchedSessions.map((s) => s.id));
    const dedupedAdditional = additionalSessions.filter(
      (s) => !firstPageIds.has(s.id)
    );

    const allFetched = [...fetchedSessions, ...dedupedAdditional];
    const allFetchedIds = new Set(allFetched.map((s) => s.id));

    // Get pending sessions that are not yet in fetched data
    const remainingPending = pendingSessions.filter(
      (pending) => !allFetchedIds.has(pending.id)
    );

    // Pending sessions go first (most recent), then fetched sessions
    return [...remainingPending, ...allFetched];
  }, [fetchedSessions, additionalSessions, pendingSessions]);

  const currentChatSessionId = appFocus.isChat() ? appFocus.getId() : null;
  const currentChatSession =
    chatSessions.find(
      (chatSession) => chatSession.id === currentChatSessionId
    ) ?? null;

  const agentForCurrentChatSession =
    useFindAgentForCurrentChatSession(currentChatSession);

  // Add a pending chat session that will persist across SWR revalidations
  // The session will be automatically removed once it appears in the server response
  const addPendingChatSession = useCallback(
    ({ chatSessionId, personaId, projectId }: PendingChatSessionParams) => {
      // Don't add sessions that belong to a project
      if (projectId != null) {
        return;
      }

      // Don't add if already in pending store (duplicates are also filtered during merge)
      if (pendingSessionsStore.has(chatSessionId)) {
        return;
      }

      // Note: This check uses stale fetchedSessions due to empty deps, but is defensive
      if (fetchedSessions.some((s) => s.id === chatSessionId)) {
        return;
      }

      const now = new Date().toISOString();
      const pendingSession: ChatSession = {
        id: chatSessionId,
        name: "", // Empty name will display as "New Chat" via UNNAMED_CHAT constant
        persona_id: personaId,
        time_created: now,
        time_updated: now,
        shared_status: ChatSessionSharedStatus.Private,
        project_id: projectId ?? null,
        current_alternate_model: "",
        current_temperature_override: null,
      };

      pendingSessionsStore.add(pendingSession);
    },
    []
  );

  const removeSession = useCallback(
    (sessionId: string) => {
      pendingSessionsStore.remove(sessionId);
      additionalSessionsStore.remove(sessionId);
      // Optimistically remove from SWR first-page cache
      mutate(
        (current) =>
          current
            ? {
                ...current,
                sessions: current.sessions.filter((s) => s.id !== sessionId),
              }
            : current,
        { revalidate: false }
      );
    },
    [mutate]
  );

  const clearAdditionalSessions = useCallback(() => {
    additionalSessionsStore.clear();
  }, []);

  return {
    chatSessions,
    currentChatSessionId,
    currentChatSession,
    agentForCurrentChatSession,
    isLoading: !error && !data,
    error,
    refreshChatSessions: mutate,
    addPendingChatSession,
    removeSession,
    clearAdditionalSessions,
    hasMore,
    isLoadingMore,
    loadMore,
  };
}
