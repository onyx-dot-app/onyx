import type { ScopedMutator } from "swr";
import { unstable_serialize } from "swr/infinite";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { NotificationsResponse } from "@/lib/notifications/interfaces";

export const DEFAULT_NOTIFICATIONS_PAGE_SIZE = 25;

export function getNotificationsPageKey(pageIndex: number): string {
  return SWR_KEYS.notificationsPage(pageIndex, DEFAULT_NOTIFICATIONS_PAGE_SIZE);
}

export function getNotificationsInfiniteKey(): string {
  return unstable_serialize(
    (
      pageIndex: number,
      previousPageData: NotificationsResponse | null
    ): string | null => {
      if (previousPageData && !previousPageData.has_more) return null;
      return getNotificationsPageKey(pageIndex);
    }
  );
}

export async function refreshNotificationCaches(
  mutate: ScopedMutator
): Promise<void> {
  await Promise.all([
    mutate(SWR_KEYS.notificationsSummary),
    mutate(getNotificationsInfiniteKey()),
  ]);
}
