import { useState, useEffect, useCallback, useRef } from "react";
import { fetchChatSessions } from "./api/client";
import { ChatSessionGroup } from "./api/models";

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
  const currentAbortController = useRef<AbortController | null>(null);
  const PAGE_SIZE = pageSize;

  const fetchInitialChats = useCallback(
    async (signal?: AbortSignal) => {
      setIsLoading(true);
      setPage(1);

      try {
        const response = await fetchChatSessions({
          query: searchQuery,
          page: 1,
          page_size: PAGE_SIZE,
          signal,
        });

        if (signal && signal.aborted) {
          return;
        }

        setChatGroups(response.groups);
        setHasMore(response.has_more);
      } catch (error) {
        if ((error as any)?.name === "AbortError") {
          console.log("Request was aborted.");
          setIsLoading(false);
          return;
        }
        console.error("Error fetching chats:", error);
      } finally {
        setIsLoading(false);
      }
    },
    [searchQuery, PAGE_SIZE]
  );

  const fetchMoreChats = useCallback(async () => {
    if (isLoading || !hasMore) return;

    setIsLoading(true);

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
        return;
      }

      setChatGroups((prev) => [...prev, ...response.groups]);
      setHasMore(response.has_more);
      setPage(nextPage);
    } catch (error) {
      if ((error as any)?.name === "AbortError") {
        console.log("Pagination request was aborted.");
        setIsLoading(false);
        return;
      }
      console.error("Error fetching more chats:", error);
    } finally {
      setIsLoading(false);
    }
  }, [isLoading, hasMore, page, searchQuery, PAGE_SIZE]);

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
          setIsSearching(false);
        });
      }, 1000);
    },
    [fetchInitialChats]
  );

  useEffect(() => {
    const controller = new AbortController();
    currentAbortController.current = controller;

    fetchInitialChats(controller.signal);

    return () => {
      // if (searchTimeoutRef.current) {
      //   clearTimeout(searchTimeoutRef.current);
      // }
      controller.abort();
    };
  }, [fetchInitialChats]);

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
