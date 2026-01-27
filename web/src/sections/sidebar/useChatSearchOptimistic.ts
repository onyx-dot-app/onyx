import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import useSWRInfinite from "swr/infinite";
import useChatSessions from "@/hooks/useChatSessions";
import { useProjects } from "@/lib/hooks/useProjects";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ChatSearchResponse } from "@/app/chat/chat_search/interfaces";
import { UNNAMED_CHAT } from "@/lib/constants";

export interface FilterableChat {
  id: string;
  label: string;
  time: string;
}

interface UseChatSearchOptimisticOptions {
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
        label: chat.name || UNNAMED_CHAT,
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

// --- Hook ---

export function useChatSearchOptimistic(
  options: UseChatSearchOptimisticOptions
): UseChatSearchOptimisticResult {
  const { searchQuery, enabled = true } = options;

  // Debounced search query for API calls
  const [debouncedQuery, setDebouncedQuery] = useState(searchQuery);

  // Ref for infinite scroll sentinel
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  // 1. Get already-cached data from existing hooks
  const { chatSessions } = useChatSessions();
  const { projects } = useProjects();

  // 2. Build combined fallback data (instant display)
  const fallbackSessions = useMemo<FilterableChat[]>(() => {
    const chatMap = new Map<string, FilterableChat>();

    // Add regular chats from useChatSessions
    for (const chat of chatSessions) {
      chatMap.set(chat.id, {
        id: chat.id,
        label: chat.name || UNNAMED_CHAT,
        time: chat.time_updated || chat.time_created,
      });
    }

    // Add project chats from useProjects
    for (const project of projects) {
      for (const chat of project.chat_sessions) {
        chatMap.set(chat.id, {
          id: chat.id,
          label: chat.name || UNNAMED_CHAT,
          time: chat.time_updated || chat.time_created,
        });
      }
    }

    // Sort by most recent
    return Array.from(chatMap.values()).sort(
      (a, b) => new Date(b.time).getTime() - new Date(a.time).getTime()
    );
  }, [chatSessions, projects]);

  // Debounce the search query
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(searchQuery), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // 3. SWR key generator for infinite scroll
  const getKey = useCallback(
    (pageIndex: number, previousPageData: ChatSearchResponse | null) => {
      // Don't fetch if not enabled
      if (!enabled) return null;

      // Reached the end
      if (previousPageData && !previousPageData.has_more) return null;

      const page = pageIndex + 1;
      const params = new URLSearchParams();
      params.set("page", page.toString());
      params.set("page_size", PAGE_SIZE.toString());

      if (debouncedQuery.trim()) {
        params.set("query", debouncedQuery);
      }

      return `/api/chat/search?${params.toString()}`;
    },
    [enabled, debouncedQuery]
  );

  // 4. Use SWR for paginated data (replaces fallback after fetch)
  const { data, size, setSize, isValidating } =
    useSWRInfinite<ChatSearchResponse>(getKey, errorHandlingFetcher, {
      revalidateOnFocus: false,
      dedupingInterval: 30000,
      revalidateFirstPage: false,
      persistSize: true,
    });

  // Transform SWR data to FilterableChat[]
  const swrResults = useMemo<FilterableChat[]>(() => {
    if (!data || data.length === 0) return [];

    const allChats: FilterableChat[] = [];
    for (const page of data) {
      allChats.push(...transformApiResponse(page));
    }

    // Deduplicate by id (keep first occurrence)
    const seen = new Set<string>();
    return allChats.filter((chat) => {
      if (seen.has(chat.id)) return false;
      seen.add(chat.id);
      return true;
    });
  }, [data]);

  // Determine if we have more pages
  const hasMore = useMemo(() => {
    if (!data || data.length === 0) return true;
    const lastPage = data[data.length - 1];
    return lastPage?.has_more ?? false;
  }, [data]);

  // 5. Return fallback if no SWR data yet, otherwise return SWR data
  const results = useMemo<FilterableChat[]>(() => {
    // If SWR has data, use it (paginated, searchable)
    if (swrResults.length > 0) {
      return swrResults;
    }

    // Otherwise use fallback (already-cached data)
    // Apply local filtering if there's a search query
    if (searchQuery.trim()) {
      return filterLocalSessions(fallbackSessions, searchQuery);
    }

    return fallbackSessions;
  }, [swrResults, fallbackSessions, searchQuery]);

  // Loading states
  const isSearching = isValidating && size === 1;
  const isLoadingMore = isValidating && size > 1;

  // Fetch more results for infinite scroll
  const fetchMore = useCallback(async () => {
    if (!enabled || isValidating || !hasMore) {
      return;
    }
    await setSize(size + 1);
  }, [enabled, isValidating, hasMore, setSize, size]);

  // IntersectionObserver for infinite scroll
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel || !enabled) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (entry?.isIntersecting && hasMore && !isValidating) {
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
  }, [enabled, hasMore, isValidating, fetchMore]);

  return {
    results,
    isSearching,
    hasMore,
    fetchMore,
    isLoadingMore,
    sentinelRef,
  };
}
