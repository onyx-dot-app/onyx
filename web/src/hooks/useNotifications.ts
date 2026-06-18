"use client";

import { useCallback, useMemo, useRef } from "react";
import useSWR, { useSWRConfig } from "swr";
import useSWRInfinite from "swr/infinite";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  Notification,
  NotificationSummary,
  NotificationsResponse,
} from "@/lib/notifications/interfaces";

const DEFAULT_NOTIFICATIONS_PAGE_SIZE = 25;

interface UseNotificationsOptions {
  pageSize?: number;
  enabled?: boolean;
}

export function useNotificationSummary() {
  const { data, error, isLoading, mutate } = useSWR<NotificationSummary>(
    SWR_KEYS.notificationsSummary,
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

      return SWR_KEYS.notificationsPage(pageIndex, pageSize);
    },
    [enabled, pageSize]
  );

  const { data, error, mutate, size, setSize } =
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
  const isLoading = enabled && !error && !data;
  const isLoadingMore =
    enabled && data !== undefined && size > 0 && data[size - 1] === undefined;
  const loadMoreInFlightRef = useRef(false);

  const loadMore = useCallback(async () => {
    if (loadMoreInFlightRef.current || isLoadingMore || !hasMore) {
      return;
    }

    loadMoreInFlightRef.current = true;
    try {
      await setSize((currentSize) => currentSize + 1);
    } catch (err) {
      console.error("Failed to load more notifications:", err);
    } finally {
      loadMoreInFlightRef.current = false;
    }
  }, [hasMore, isLoadingMore, setSize]);

  const refresh = useCallback(() => {
    void mutateGlobal(SWR_KEYS.notificationsSummary);
    if (!enabled) return Promise.resolve(undefined);

    return mutate();
  }, [enabled, mutate, mutateGlobal]);

  return {
    notifications,
    undismissedCount,
    totalItems,
    isLoading,
    error,
    refresh,
    hasMore,
    isLoadingMore,
    loadMore,
  };
}
