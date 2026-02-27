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
  hasMore: boolean;
  isLoadingMore: boolean;
  loadMore: () => void;
}

// Module-level store for pending chat sessions
// This persists across SWR revalidations and component re-renders
// Pending sessions are shown in the sidebar until the server returns them
const pendingSessionsStore = {
  sessions: new Map<string, ChatSession>(),
  listeners: new Set<() => void>(),
  // Cached snapshot to avoid creating new array references on every call
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

// Stable empty array for SSR - must be defined outside component to avoid infinite loop
const EMPTY_SESSIONS: ChatSession[] = [];

function usePendingSessions(): ChatSession[] {
  return useSyncExternalStore(
    (callback) => pendingSessionsStore.subscribe(callback),
    () => pendingSessionsStore.getSnapshot(),
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
  const fetchedSessions = data?.sessions ?? [];

  // State for additional pages loaded via infinite scroll.
  const [additionalSessions, setAdditionalSessions] = useState<ChatSession[]>(
    []
  );
  const [hasMore, setHasMore] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);

  // Sync hasMore from the initial SWR response when no additional pages loaded yet
  useEffect(() => {
    if (data && additionalSessions.length === 0) {
      setHasMore(data.has_more);
    }
  }, [data, additionalSessions.length]);

  const loadMore = useCallback(async () => {
    if (isLoadingMore || !hasMore) return;

    const currentOffset = fetchedSessions.length + additionalSessions.length;
    setIsLoadingMore(true);
    const loadStart = Date.now();

    try {
      const params = new URLSearchParams({
        page_size: PAGE_SIZE.toString(),
        offset: currentOffset.toString(),
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

      setAdditionalSessions((prev) => [...prev, ...response.sessions]);
      setHasMore(response.has_more);
    } catch (err) {
      console.error("Failed to load more chat sessions:", err);
    } finally {
      setIsLoadingMore(false);
    }
  }, [
    fetchedSessions.length,
    additionalSessions.length,
    isLoadingMore,
    hasMore,
  ]);

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

  return {
    chatSessions,
    currentChatSessionId,
    currentChatSession,
    agentForCurrentChatSession,
    isLoading: !error && !data,
    error,
    refreshChatSessions: mutate,
    addPendingChatSession,
    hasMore,
    isLoadingMore,
    loadMore,
  };
}
