import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { fetchChatSessions, createNewChat, deleteChat } from "./api/client";
import { ChatSessionGroup, ChatSessionSummary } from "./api/models";

interface UseChatSearchOptions {
  includeHighlights?: boolean;
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
  const { includeHighlights = true, pageSize = 10 } = options;
  const [searchQuery, setSearchQuery] = useState("");
  const [chatGroups, setChatGroups] = useState<ChatSessionGroup[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [page, setPage] = useState(1);
  const searchTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const PAGE_SIZE = pageSize;

  // Initial fetch
  const fetchInitialChats = useCallback(async () => {
    setIsLoading(true);
    setPage(1);

    try {
      const response = await fetchChatSessions({
        query: searchQuery,
        page: 1,
        page_size: PAGE_SIZE,
        include_highlights: includeHighlights,
      });

      setChatGroups(response.groups);
      setHasMore(response.has_more);
    } catch (error) {
      console.error("Error fetching chats:", error);
    } finally {
      setIsLoading(false);
    }
  }, [searchQuery, PAGE_SIZE, includeHighlights]);

  // Load more chats (pagination)
  const fetchMoreChats = useCallback(async () => {
    if (isLoading || !hasMore) return;

    setIsLoading(true);

    try {
      const nextPage = page + 1;
      const response = await fetchChatSessions({
        query: searchQuery,
        page: nextPage,
        page_size: PAGE_SIZE,
        include_highlights: includeHighlights,
      });

      setChatGroups((prev) => [...prev, ...response.groups]);
      setHasMore(response.has_more);
      setPage(nextPage);
    } catch (error) {
      console.error("Error fetching more chats:", error);
    } finally {
      setIsLoading(false);
    }
  }, [isLoading, hasMore, page, searchQuery, PAGE_SIZE, includeHighlights]);

  // Handle search with debounce
  const handleSearch = useCallback(
    (query: string) => {
      setSearchQuery(query);

      if (searchTimeoutRef.current) {
        clearTimeout(searchTimeoutRef.current);
      }

      setIsSearching(true);

      // searchTimeoutRef.current =
      setTimeout(() => {
        fetchInitialChats();
        setIsSearching(false);
      }, 1000);
    },
    [fetchInitialChats]
  );

  // Initial load
  useEffect(() => {
    fetchInitialChats();

    return () => {
      if (searchTimeoutRef.current) {
        clearTimeout(searchTimeoutRef.current);
      }
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
    refreshChats: fetchInitialChats,
  };
}
