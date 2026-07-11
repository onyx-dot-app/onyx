"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import useSWRInfinite from "swr/infinite";
import { useSettings } from "@/lib/settings/hooks";
import useChatSessions from "@/hooks/useChatSessions";
import { useProjects } from "@/lib/projects/hooks";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ChatSearchResponse } from "@/app/app/interfaces";
import { UNNAMED_CHAT } from "@/lib/constants";
import { SWR_KEYS } from "@/lib/swr-keys";

// ---------------------------------------------------------------------------
// useShowLogoWhenFolded
// ---------------------------------------------------------------------------

/**
 * Returns whether the app logo should remain visible in the sidebar when it
 * is folded. When an enterprise `logo_display_style` of `"name_only"` is
 * configured, the logo is hidden in the folded state so only the text name
 * would be shown — but since there's no room for text when folded, the logo
 * is suppressed entirely in that case.
 */
export function useShowLogoWhenFolded(): boolean {
  const settings = useSettings();
  return settings.enterprise?.logo_display_style !== "name_only";
}

// ---------------------------------------------------------------------------
// useChatSearchOptimistic
// ---------------------------------------------------------------------------

interface FilterableChat {
  id: string;
  label: string;
  time: string;
}

interface UseChatSearchOptimisticOptions {
  searchQuery: string;
  /** When `false`, no API calls are made and the hook returns only locally
   *  cached data. Defaults to `true`. */
  enabled?: boolean;
}

interface UseChatSearchOptimisticResult {
  /** Merged, deduplicated, sorted list of matching chats. */
  results: FilterableChat[];
  /** `true` while the first API page is loading. */
  isSearching: boolean;
  /** `true` when there are additional pages to fetch. */
  hasMore: boolean;
  /** Fetches the next page of results. */
  fetchMore: () => Promise<void>;
  /** `true` while a subsequent (non-first) page is loading. */
  isLoadingMore: boolean;
  /** Attach to the sentinel element to trigger infinite scroll. */
  sentinelRef: React.RefObject<HTMLDivElement | null>;
}

const PAGE_SIZE = 20;
const DEBOUNCE_MS = 300;

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
  if (!searchQuery.trim()) return sessions;
  const term = searchQuery.toLowerCase();
  return sessions.filter((chat) => chat.label.toLowerCase().includes(term));
}

/**
 * Optimistic search over chat sessions and projects.
 *
 * The hook immediately returns results from the already-cached SWR data
 * (instant display), then replaces them with paginated API results as they
 * arrive. While no SWR data is available the hook filters the locally cached
 * sessions instead, giving a snappy feel even on slow connections.
 *
 * Infinite scroll is driven by an `IntersectionObserver` attached to the
 * `sentinelRef` element — place it at the bottom of the result list.
 */
export default function useChatSearchOptimistic(
  options: UseChatSearchOptimisticOptions
): UseChatSearchOptimisticResult {
  const { searchQuery, enabled = true } = options;

  const [debouncedQuery, setDebouncedQuery] = useState(searchQuery);
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  const { chatSessions } = useChatSessions();
  const { projects } = useProjects();

  const fallbackSessions = useMemo<FilterableChat[]>(() => {
    const chatMap = new Map<string, FilterableChat>();

    for (const chat of chatSessions) {
      chatMap.set(chat.id, {
        id: chat.id,
        label: chat.name || UNNAMED_CHAT,
        time: chat.time_updated || chat.time_created,
      });
    }

    for (const project of projects) {
      for (const chat of project.chat_sessions) {
        chatMap.set(chat.id, {
          id: chat.id,
          label: chat.name || UNNAMED_CHAT,
          time: chat.time_updated || chat.time_created,
        });
      }
    }

    return Array.from(chatMap.values()).sort(
      (a, b) => new Date(b.time).getTime() - new Date(a.time).getTime()
    );
  }, [chatSessions, projects]);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(searchQuery), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const getKey = useCallback(
    (pageIndex: number, previousPageData: ChatSearchResponse | null) => {
      if (!enabled) return null;
      if (previousPageData && !previousPageData.has_more) return null;

      const page = pageIndex + 1;
      const params = new URLSearchParams();
      params.set("page", page.toString());
      params.set("page_size", PAGE_SIZE.toString());
      if (debouncedQuery.trim()) params.set("query", debouncedQuery);

      return `${SWR_KEYS.chatSearch}?${params.toString()}`;
    },
    [enabled, debouncedQuery]
  );

  const { data, size, setSize, isValidating } =
    useSWRInfinite<ChatSearchResponse>(getKey, errorHandlingFetcher, {
      revalidateOnFocus: false,
      dedupingInterval: 30000,
      revalidateFirstPage: false,
      persistSize: true,
    });

  const swrResults = useMemo<FilterableChat[]>(() => {
    if (!data || data.length === 0) return [];

    const allChats: FilterableChat[] = [];
    for (const page of data) allChats.push(...transformApiResponse(page));

    const seen = new Set<string>();
    return allChats.filter((chat) => {
      if (seen.has(chat.id)) return false;
      seen.add(chat.id);
      return true;
    });
  }, [data]);

  const hasMore = useMemo(() => {
    if (!data || data.length === 0) return true;
    return data[data.length - 1]?.has_more ?? false;
  }, [data]);

  const results = useMemo<FilterableChat[]>(() => {
    if (swrResults.length > 0) return swrResults;
    if (searchQuery.trim())
      return filterLocalSessions(fallbackSessions, searchQuery);
    return fallbackSessions;
  }, [swrResults, fallbackSessions, searchQuery]);

  const isSearching = isValidating && size === 1;
  const isLoadingMore = isValidating && size > 1;

  const fetchMore = useCallback(async () => {
    if (!enabled || isValidating || !hasMore) return;
    await setSize(size + 1);
  }, [enabled, isValidating, hasMore, setSize, size]);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel || !enabled) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (entry?.isIntersecting && hasMore && !isValidating) fetchMore();
      },
      { root: null, rootMargin: "100px", threshold: 0 }
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
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
