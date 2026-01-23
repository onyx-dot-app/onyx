import { useState, useEffect, useCallback, useRef } from "react";
import { fetchChatSessions } from "../utils";
import { ChatSessionGroup, ChatSessionSummary } from "../interfaces";

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
  const [searchQuery, setSearchQueryInternal] = useState("");
  const [chatGroups, setChatGroups] = useState<ChatSessionGroup[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [debouncedIsSearching, setDebouncedIsSearching] = useState(false);

  const [page, setPage] = useState(1);
  const searchTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const currentAbortController = useRef<AbortController | null>(null);
  const activeSearchIdRef = useRef<number>(0); // Add a unique ID for each search
  const PAGE_SIZE = pageSize;

  useEffect(() => {
    // Only set a timeout if we're not already in the desired state
    if (!isSearching) {
      const timeout = setTimeout(() => {
        setDebouncedIsSearching(isSearching);
      }, 300);

      // Keep track of the timeout reference to clear it on cleanup
      const timeoutRef = timeout;

      return () => clearTimeout(timeoutRef);
    } else {
      setDebouncedIsSearching(isSearching);
    }
  }, [isSearching, debouncedIsSearching]);

  // Helper function to merge groups properly
  const mergeGroups = useCallback(
    (
      existingGroups: ChatSessionGroup[],
      newGroups: ChatSessionGroup[]
    ): ChatSessionGroup[] => {
      const mergedGroups: Record<string, ChatSessionSummary[]> = {};

      // Initialize with existing groups
      existingGroups.forEach((group) => {
        mergedGroups[group.title] = [
          ...(mergedGroups[group.title] || []),
          ...group.chats,
        ];
      });

      // Merge in new groups
      newGroups.forEach((group) => {
        mergedGroups[group.title] = [
          ...(mergedGroups[group.title] || []),
          ...group.chats,
        ];
      });

      // Convert back to array format
      return Object.entries(mergedGroups)
        .map(([title, chats]) => ({ title, chats }))
        .sort((a, b) => {
          // Custom sort order for time periods
          const order = [
            "Today",
            "Yesterday",
            "This Week",
            "This Month",
            "Older",
          ];
          return order.indexOf(a.title) - order.indexOf(b.title);
        });
    },
    []
  );

  const fetchInitialChats = useCallback(
    async (query: string, searchId: number, signal?: AbortSignal) => {
      try {
        setIsLoading(true);
        setPage(1);

        const response = await fetchChatSessions({
          query,
          page: 1,
          page_size: PAGE_SIZE,
          signal,
        });

        // Only update state if this is still the active search
        if (activeSearchIdRef.current === searchId && !signal?.aborted) {
          setChatGroups(response.groups);
          setHasMore(response.has_more);
        }
      } catch (error: any) {
        if (
          error?.name !== "AbortError" &&
          activeSearchIdRef.current === searchId
        ) {
          console.error("Error fetching chats:", error);
        }
      } finally {
        // Only update loading state if this is still the active search
        if (activeSearchIdRef.current === searchId) {
          setIsLoading(false);
          setIsSearching(false);
        }
      }
    },
    [PAGE_SIZE]
  );

  const fetchMoreChats = useCallback(async () => {
    if (isLoading || !hasMore) return;

    setIsLoading(true);

    if (currentAbortController.current) {
      currentAbortController.current.abort();
    }

    const newSearchId = activeSearchIdRef.current + 1;
    activeSearchIdRef.current = newSearchId;

    const controller = new AbortController();
    currentAbortController.current = controller;
    const localSignal = controller.signal;

    try {
      const nextPage = page + 1;
      const response = await fetchChatSessions({
        query: searchQuery,
        page: nextPage,
        page_size: PAGE_SIZE,
        signal: localSignal,
      });

      if (activeSearchIdRef.current === newSearchId && !localSignal.aborted) {
        // Use mergeGroups instead of just concatenating
        setChatGroups((prevGroups) => mergeGroups(prevGroups, response.groups));
        setHasMore(response.has_more);
        setPage(nextPage);
      }
    } catch (error: any) {
      if (
        error?.name !== "AbortError" &&
        activeSearchIdRef.current === newSearchId
      ) {
        console.error("Error fetching more chats:", error);
      }
    } finally {
      if (activeSearchIdRef.current === newSearchId) {
        setIsLoading(false);
      }
    }
  }, [isLoading, hasMore, page, searchQuery, PAGE_SIZE, mergeGroups]);

  const setSearchQuery = useCallback(
    (query: string) => {
      setSearchQueryInternal(query);

      // Clear any pending timeouts
      if (searchTimeoutRef.current) {
        clearTimeout(searchTimeoutRef.current);
        searchTimeoutRef.current = null;
      }

      // Abort any in-flight requests
      if (currentAbortController.current) {
        currentAbortController.current.abort();
        currentAbortController.current = null;
      }

      // Create a new search ID
      const newSearchId = activeSearchIdRef.current + 1;
      activeSearchIdRef.current = newSearchId;

      if (query.trim()) {
        setIsSearching(true);

        const controller = new AbortController();
        currentAbortController.current = controller;

        searchTimeoutRef.current = setTimeout(() => {
          fetchInitialChats(query, newSearchId, controller.signal);
        }, 500);
      } else {
        // For empty queries, clear search state immediately
        setIsSearching(false);
        // Optionally fetch initial unfiltered results
        fetchInitialChats("", newSearchId);
      }
    },
    [fetchInitialChats]
  );

  // Initial fetch on mount
  useEffect(() => {
    const newSearchId = activeSearchIdRef.current + 1;
    activeSearchIdRef.current = newSearchId;

    const controller = new AbortController();
    currentAbortController.current = controller;

    fetchInitialChats(searchQuery, newSearchId, controller.signal);

    return () => {
      if (searchTimeoutRef.current) {
        clearTimeout(searchTimeoutRef.current);
      }
      controller.abort();
    };
  }, [fetchInitialChats, searchQuery]);

  return {
    searchQuery,
    setSearchQuery,
    chatGroups,
    isLoading,
    isSearching: debouncedIsSearching,
    hasMore,
    fetchMoreChats,
    refreshChats: () => {
      const newSearchId = activeSearchIdRef.current + 1;
      activeSearchIdRef.current = newSearchId;

      if (currentAbortController.current) {
        currentAbortController.current.abort();
      }

      const controller = new AbortController();
      currentAbortController.current = controller;

      return fetchInitialChats(searchQuery, newSearchId, controller.signal);
    },
  };
}
