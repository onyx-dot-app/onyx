"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { Notification } from "@/lib/notifications/interfaces";

/**
 * Fetches the current user's notifications.
 *
 * The GET endpoint also triggers a server-side refresh if release notes
 * are stale, so simply mounting this hook keeps notifications up to date.
 *
 * @returns Object containing:
 *   - notifications: Array of Notification objects (empty array while loading)
 *   - undismissedCount: Number of notifications that haven't been dismissed
 *   - isLoading: Boolean indicating if data is being fetched
 *   - error: Any error that occurred during fetch
 *   - refresh: Function to manually revalidate the data
 */
export default function useNotifications() {
  const { data, error, isLoading, mutate } = useSWR<Notification[]>(
    SWR_KEYS.notifications,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );

  const notifications = data ?? [];
  const undismissedCount = notifications.filter((n) => !n.dismissed).length;

  return {
    notifications,
    undismissedCount,
    isLoading,
    error,
    refresh: mutate,
  };
}
