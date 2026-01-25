import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { fetchChatSessions } from "@/app/chat/chat_search/utils";
import { ChatSearchResponse } from "@/app/chat/chat_search/interfaces";

export interface FilterableChat {
  id: string;
  label: string;
  time: string;
}

interface UseChatSearchOptimisticOptions {
  localSessions: FilterableChat[];
  searchQuery: string;
  enabled?: boolean;
}

interface UseChatSearchOptimisticResult {
  results: FilterableChat[];
  isSearching: boolean;
  hasMore: boolean;
  fetchMore: () => Promise<void>;
  isLoadingMore: boolean;
  sentinelRef: React.RefObject<HTMLDivElement | null>;
}

const PAGE_SIZE = 20;
const DEBOUNCE_MS = 300;

// --- Helper Functions ---

function transformApiResponse(response: ChatSearchResponse): FilterableChat[] {
  const chats: FilterableChat[] = [];
  for (const group of response.groups) {
    for (const chat of group.chats) {
      chats.push({
        id: chat.id,
        label: chat.name || "New Chat",
        time: chat.time_created,
      });
    }
  }
  return chats;
}

function filterLocalSessions(
  sessions: FilterableChat[],
  searchQuery: string
): FilterableChat[] {
  if (!searchQuery.trim()) {
    return sessions;
  }
  const term = searchQuery.toLowerCase();
  return sessions.filter((chat) => chat.label.toLowerCase().includes(term));
}

function mergeResults(
  localResults: FilterableChat[],
  remoteResults: FilterableChat[]
): FilterableChat[] {
  if (remoteResults.length === 0) {
    return localResults;
  }

  // Create a map with local results first, then overlay remote results
  const resultMap = new Map<string, FilterableChat>();

  for (const chat of localResults) {
    resultMap.set(chat.id, chat);
  }

  // Remote results take priority (overwrite local)
  for (const chat of remoteResults) {
    resultMap.set(chat.id, chat);
  }

  // Sort by time (most recent first)
  return Array.from(resultMap.values()).sort(
    (a, b) => new Date(b.time).getTime() - new Date(a.time).getTime()
  );
}

// --- Hook ---

export function useChatSearchOptimistic(
  options: UseChatSearchOptimisticOptions
): UseChatSearchOptimisticResult {
  const { localSessions, searchQuery, enabled = true } = options;

  // Remote search state
  const [remoteResults, setRemoteResults] = useState<FilterableChat[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);

  // Refs for request management
  const searchTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const activeSearchIdRef = useRef<number>(0);

  // Ref for infinite scroll sentinel
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  // Optimistic local filtering (immediate)
  const localFilteredResults = useMemo(
    () => filterLocalSessions(localSessions, searchQuery),
    [localSessions, searchQuery]
  );

  // Merge local and remote results
  const mergedResults = useMemo(
    () => mergeResults(localFilteredResults, remoteResults),
    [localFilteredResults, remoteResults]
  );

  // Fetch from remote API
  const fetchRemote = useCallback(
    async (query: string, page: number, searchId: number, append: boolean) => {
      const controller = new AbortController();
      abortControllerRef.current = controller;

      try {
        const response = await fetchChatSessions({
          query,
          page,
          page_size: PAGE_SIZE,
          signal: controller.signal,
        });

        // Only update state if this is still the active search
        if (
          activeSearchIdRef.current === searchId &&
          !controller.signal.aborted
        ) {
          const transformed = transformApiResponse(response);

          if (append) {
            setRemoteResults((prev) => [...prev, ...transformed]);
          } else {
            setRemoteResults(transformed);
          }

          setHasMore(response.has_more);
          setCurrentPage(page);
        }
      } catch (error: unknown) {
        const err = error as { name?: string };
        if (
          err?.name !== "AbortError" &&
          activeSearchIdRef.current === searchId
        ) {
          console.error("Error fetching chat sessions:", error);
        }
      } finally {
        if (activeSearchIdRef.current === searchId) {
          setIsSearching(false);
          setIsLoadingMore(false);
        }
      }
    },
    []
  );

  // Effect to handle search query changes
  useEffect(() => {
    if (!enabled) {
      return;
    }

    // Clear pending timeout
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
      searchTimeoutRef.current = null;
    }

    // Abort in-flight requests
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    // Reset state when query changes
    setRemoteResults([]);
    setCurrentPage(1);

    if (searchQuery.trim()) {
      // Has search query: fetch from API with debounce
      setHasMore(false);
      setIsSearching(true);

      const newSearchId = activeSearchIdRef.current + 1;
      activeSearchIdRef.current = newSearchId;

      searchTimeoutRef.current = setTimeout(() => {
        fetchRemote(searchQuery, 1, newSearchId, false);
      }, DEBOUNCE_MS);
    } else {
      // No search query: browse mode
      // Always enable hasMore - let fetchMore/API determine actual value
      setIsSearching(false);
      setHasMore(true);
    }

    return () => {
      if (searchTimeoutRef.current) {
        clearTimeout(searchTimeoutRef.current);
      }
    };
  }, [searchQuery, enabled, fetchRemote, localSessions.length]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (searchTimeoutRef.current) {
        clearTimeout(searchTimeoutRef.current);
      }
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  // Fetch more results for infinite scroll
  const fetchMore = useCallback(async () => {
    if (!enabled || isLoadingMore || isSearching || !hasMore) {
      return;
    }

    const newSearchId = activeSearchIdRef.current + 1;
    activeSearchIdRef.current = newSearchId;

    setIsLoadingMore(true);

    let nextPage: number;
    if (remoteResults.length === 0) {
      // First fetch in browse mode: skip pages covered by local sessions
      // e.g., 50 local items / 20 page size = page 3 (items 41-60)
      nextPage = Math.floor(localSessions.length / PAGE_SIZE) + 1;
    } else {
      nextPage = currentPage + 1;
    }

    await fetchRemote(searchQuery, nextPage, newSearchId, true);
  }, [
    enabled,
    isLoadingMore,
    isSearching,
    hasMore,
    searchQuery,
    currentPage,
    remoteResults.length,
    localSessions.length,
    fetchRemote,
  ]);

  // IntersectionObserver for infinite scroll
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel || !enabled) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (
          entry?.isIntersecting &&
          hasMore &&
          !isLoadingMore &&
          !isSearching
        ) {
          fetchMore();
        }
      },
      {
        root: null,
        rootMargin: "100px",
        threshold: 0,
      }
    );

    observer.observe(sentinel);

    return () => {
      observer.disconnect();
    };
  }, [enabled, hasMore, isLoadingMore, isSearching, fetchMore]);

  return {
    results: mergedResults,
    isSearching,
    hasMore,
    fetchMore,
    isLoadingMore,
    sentinelRef,
  };
}
