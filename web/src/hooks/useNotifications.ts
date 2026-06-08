"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import useSWRInfinite from "swr/infinite";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  NotificationType,
  Notification,
  NotificationSummary,
  NotificationsResponse,
} from "@/lib/notifications/interfaces";

const DEFAULT_NOTIFICATIONS_PAGE_SIZE = 25;
const NOTIFICATIONS_SUMMARY_URL = `${SWR_KEYS.notifications}/summary`;

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
  const { data, error, isLoading, mutate } = useSWR<NotificationSummary>(
    NOTIFICATIONS_SUMMARY_URL,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
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
 * The first page can also trigger server-side checks that create notifications.
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
  const firstPageKey = useMemo(
    () =>
      buildNotificationsUrl({
        pageNum: 0,
        pageSize,
        notificationType,
      }),
    [notificationType, pageSize]
  );
  const getKey = useCallback(
    (
      pageIndex: number,
      previousPageData: NotificationsResponse | null
    ): string | null => {
      if (!enabled) return null;
      if (previousPageData && !previousPageData.has_more) return null;

      if (pageIndex === 0) return firstPageKey;

      return buildNotificationsUrl({
        pageNum: pageIndex,
        pageSize,
        notificationType,
      });
    },
    [enabled, firstPageKey, notificationType, pageSize]
  );

  const { data, error, mutate, setSize } =
    useSWRInfinite<NotificationsResponse>(getKey, errorHandlingFetcher, {
      revalidateOnFocus: false,
      revalidateFirstPage: false,
      revalidateAll: false,
      dedupingInterval: 30000,
    });

  const notifications = useMemo<Notification[]>(() => {
    if (!data) return [];

    const seenNotificationIds = new Set<number>();
    return data.flatMap((page) =>
      page.notifications.filter((notification) => {
        if (seenNotificationIds.has(notification.id)) {
          return false;
        }
        seenNotificationIds.add(notification.id);
        return true;
      })
    );
  }, [data]);
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
    void mutateGlobal(NOTIFICATIONS_SUMMARY_URL);
    if (!enabled) return Promise.resolve(undefined);

    return mutate((currentData) => currentData, {
      populateCache: false,
      revalidate: true,
    });
  }, [enabled, mutate, mutateGlobal]);

  return {
    notifications,
    undismissedCount,
    totalItems,
    isLoading: enabled && !error && !data,
    error,
    refresh,
    hasMore,
    isLoadingMore,
    loadMore,
  };
}
