"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import useSWRInfinite from "swr/infinite";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  NotificationType,
  Notification,
  NotificationsResponse,
} from "@/lib/notifications/interfaces";

const DEFAULT_NOTIFICATIONS_PAGE_SIZE = 25;
const NOTIFICATIONS_SUMMARY_PAGE_SIZE = 1;

function buildNotificationsUrl({
  pageNum,
  pageSize,
  notificationType,
}: {
  pageNum: number;
  pageSize: number;
  notificationType?: NotificationType;
}): string {
  const params = new URLSearchParams({
    page_num: pageNum.toString(),
    page_size: pageSize.toString(),
  });
  if (notificationType) {
    params.set("notif_type", notificationType);
  }
  return `${SWR_KEYS.notifications}?${params.toString()}`;
}

interface UseNotificationsOptions {
  pageSize?: number;
  notificationType?: NotificationType;
  enabled?: boolean;
}

export function useNotificationSummary() {
  const summaryKey = buildNotificationsUrl({
    pageNum: 0,
    pageSize: NOTIFICATIONS_SUMMARY_PAGE_SIZE,
  });
  const { data, error, isLoading, mutate } = useSWR<NotificationsResponse>(
    summaryKey,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateIfStale: false,
      dedupingInterval: 30000,
    }
  );

  return {
    totalItems: data?.total_items ?? 0,
    undismissedCount: data?.undismissed_count ?? 0,
    isLoading,
    error,
    refresh: mutate,
  };
}

/**
 * Fetches the current user's notifications.
 *
 * The GET endpoint also triggers a server-side refresh if release notes
 * are stale, so simply mounting this hook keeps notifications up to date.
 *
 * @returns Object containing:
 *   - notifications: Array of Notification objects (empty array while loading)
 *   - undismissedCount: Number of notifications that haven't been dismissed
 *   - totalItems: Total number of matching notifications
 *   - isLoading: Boolean indicating if data is being fetched
 *   - error: Any error that occurred during fetch
 *   - refresh: Function to manually revalidate the data
 *   - hasMore: Whether another page is available
 *   - isLoadingMore: Whether a subsequent page is loading
 *   - loadMore: Function to fetch the next page
 */
export default function useNotifications({
  pageSize = DEFAULT_NOTIFICATIONS_PAGE_SIZE,
  notificationType,
  enabled = true,
}: UseNotificationsOptions = {}) {
  const { mutate: mutateGlobal } = useSWRConfig();
  const getKey = useCallback(
    (
      pageIndex: number,
      previousPageData: NotificationsResponse | null
    ): string | null => {
      if (!enabled) return null;
      if (previousPageData && !previousPageData.has_more) return null;

      return buildNotificationsUrl({
        pageNum: pageIndex,
        pageSize,
        notificationType,
      });
    },
    [enabled, notificationType, pageSize]
  );

  const { data, error, mutate, setSize } =
    useSWRInfinite<NotificationsResponse>(getKey, errorHandlingFetcher, {
      revalidateOnFocus: false,
      revalidateIfStale: false,
      revalidateFirstPage: false,
      revalidateAll: false,
      dedupingInterval: 30000,
    });

  const notifications = useMemo<Notification[]>(
    () => (data ? data.flatMap((page) => page.notifications) : []),
    [data]
  );
  const firstPage = data?.[0];
  const lastPage = data?.[data.length - 1];
  const undismissedCount = firstPage?.undismissed_count ?? 0;
  const totalItems = firstPage?.total_items ?? 0;
  const hasMore = lastPage?.has_more ?? false;
  const loadedPageCount = data?.length ?? 0;
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const loadedPageCountRef = useRef(loadedPageCount);
  const hasMoreRef = useRef(hasMore);
  const requestedPageCountRef = useRef(loadedPageCount);
  const loadMoreInFlightRef = useRef(false);

  useEffect(() => {
    loadedPageCountRef.current = loadedPageCount;
    hasMoreRef.current = hasMore;

    if (loadedPageCount >= requestedPageCountRef.current) {
      loadMoreInFlightRef.current = false;
      setIsLoadingMore(false);
    }
  }, [hasMore, loadedPageCount]);

  const loadMore = useCallback(async () => {
    const currentLoadedPageCount = loadedPageCountRef.current;
    if (
      loadMoreInFlightRef.current ||
      requestedPageCountRef.current > currentLoadedPageCount ||
      !hasMoreRef.current
    ) {
      return;
    }

    const nextPageCount = currentLoadedPageCount + 1;
    requestedPageCountRef.current = nextPageCount;
    loadMoreInFlightRef.current = true;
    setIsLoadingMore(true);
    try {
      await setSize(nextPageCount);
    } catch (err) {
      requestedPageCountRef.current = currentLoadedPageCount;
      loadMoreInFlightRef.current = false;
      setIsLoadingMore(false);
      console.error("Failed to load more notifications:", err);
    }
  }, [setSize]);

  const refresh = useCallback(() => {
    mutateGlobal(
      buildNotificationsUrl({
        pageNum: 0,
        pageSize: NOTIFICATIONS_SUMMARY_PAGE_SIZE,
      })
    );
    return mutate();
  }, [mutate, mutateGlobal]);

  return {
    notifications,
    undismissedCount,
    totalItems,
    isLoading: !error && !data,
    error,
    refresh,
    hasMore,
    isLoadingMore,
    loadMore,
  };
}
