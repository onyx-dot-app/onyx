import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { fetchChatSessions, createNewChat, deleteChat } from "./api/client";
import { ChatSessionGroup, ChatSessionSummary } from "./api/models";

interface UseChatSearchOptions {
  pageSize?: number;
}

interface UseChatSearchResult {
  searchQuery: string;
  setSearchQuery: (query: string) => void;
  chatGroups: ChatSessionGroup[];
  isLoading: boolean;
  isSearching: boolean;
  hasMore: boolean;
  fetchMoreChats: () => Promise<void>;
  refreshChats: () => Promise<void>;
}

export function useChatSearch(
  options: UseChatSearchOptions = {}
): UseChatSearchResult {
  const { pageSize = 10 } = options;
  const [searchQuery, setSearchQuery] = useState("");
  const [chatGroups, setChatGroups] = useState<ChatSessionGroup[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [page, setPage] = useState(1);
  const searchTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const PAGE_SIZE = pageSize;

  // NEW: Keep a reference to the current AbortController so we can cancel any
  // ongoing request when a new request starts.
  const currentAbortController = useRef<AbortController | null>(null);

  // ---------------------------------------------------------------------------
  // 1. Fetch function that can be aborted
  // ---------------------------------------------------------------------------
  const fetchInitialChats = useCallback(
    async (signal?: AbortSignal) => {
      setIsLoading(true);
      setPage(1);

      try {
        const response = await fetchChatSessions({
          query: searchQuery,
          page: 1,
          page_size: PAGE_SIZE,
          // Pass the signal to your fetch or other HTTP client if supported
          signal, // <--- This is key if your fetchChatSessions can handle AbortSignal
        });

        // If the request was aborted, signal.aborted will be true
        if (signal && signal.aborted) {
          return; // Do not update state if this request is canceled
        }

        setChatGroups(response.groups);
        setHasMore(response.has_more);
      } catch (error) {
        // If the fetch was aborted, the error might be an AbortError depending on your environment:
        if ((error as any)?.name === "AbortError") {
          console.log("Request was aborted.");
          return;
        }
        console.error("Error fetching chats:", error);
      } finally {
        setIsLoading(false);
      }
    },
    [searchQuery, PAGE_SIZE]
  );

  // ---------------------------------------------------------------------------
  // 2. Pagination
  // ---------------------------------------------------------------------------
  const fetchMoreChats = useCallback(async () => {
    if (isLoading || !hasMore) return;

    setIsLoading(true);

    // Because "fetchMoreChats" is typically triggered by scrolling,
    // you might choose not to cancel previous requests here. But you *can* do so
    // if you want only one in-flight request at a time:
    if (currentAbortController.current) {
      currentAbortController.current.abort();
    }
    currentAbortController.current = new AbortController();
    const localSignal = currentAbortController.current.signal;

    try {
      const nextPage = page + 1;
      const response = await fetchChatSessions({
        query: searchQuery,
        page: nextPage,
        page_size: PAGE_SIZE,
        signal: localSignal,
      });

      if (localSignal.aborted) {
        return; // if aborted, do not update state
      }

      setChatGroups((prev) => [...prev, ...response.groups]);
      setHasMore(response.has_more);
      setPage(nextPage);
    } catch (error) {
      if ((error as any)?.name === "AbortError") {
        console.log("Pagination request was aborted.");
        return;
      }
      console.error("Error fetching more chats:", error);
    } finally {
      setIsLoading(false);
    }
  }, [isLoading, hasMore, page, searchQuery, PAGE_SIZE]);

  // ---------------------------------------------------------------------------
  // 3. Debounced search
  // ---------------------------------------------------------------------------
  const handleSearch = useCallback(
    (query: string) => {
      setSearchQuery(query);

      if (searchTimeoutRef.current) {
        clearTimeout(searchTimeoutRef.current);
      }

      if (currentAbortController.current) {
        currentAbortController.current.abort();
      }
      currentAbortController.current = new AbortController();
      const localSignal = currentAbortController.current.signal;

      setIsSearching(true);

      searchTimeoutRef.current = setTimeout(() => {
        fetchInitialChats(localSignal).finally(() => {
          // Always revert to false when the request finishes—aborted or not
          setIsSearching(false);
        });
      }, 1000);
    },
    [fetchInitialChats]
  );

  // ---------------------------------------------------------------------------
  // 4. Initial load (runs on mount / whenever fetchInitialChats changes)
  // ---------------------------------------------------------------------------
  useEffect(() => {
    // When component mounts or the effect re-runs, fetch initial data
    // Typically not searching yet, so no debounce needed here
    const controller = new AbortController();
    currentAbortController.current = controller;

    fetchInitialChats(controller.signal);

    // Cleanup: if component unmounts or re-renders, abort the request
    return () => {
      if (searchTimeoutRef.current) {
        clearTimeout(searchTimeoutRef.current);
      }
      controller.abort();
    };
  }, [fetchInitialChats]);

  // ---------------------------------------------------------------------------
  // 5. Expose result
  // ---------------------------------------------------------------------------
  return {
    searchQuery,
    setSearchQuery: handleSearch,
    chatGroups,
    isLoading,
    isSearching,
    hasMore,
    fetchMoreChats,
    refreshChats: () =>
      fetchInitialChats(currentAbortController.current?.signal),
  };
}
