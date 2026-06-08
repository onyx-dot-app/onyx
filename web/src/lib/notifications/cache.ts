import type { ScopedMutator } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";

const INFINITE_NOTIFICATIONS_KEY_PREFIX = `$inf$${SWR_KEYS.notifications}?`;

function isNotificationsPageCacheKey(key: unknown): boolean {
  return (
    typeof key === "string" &&
    (key.startsWith(`${SWR_KEYS.notifications}?`) ||
      key.startsWith(INFINITE_NOTIFICATIONS_KEY_PREFIX))
  );
}

export async function refreshNotificationCaches(
  mutate: ScopedMutator
): Promise<void> {
  await Promise.all([
    mutate(SWR_KEYS.notificationsSummary),
    mutate((key) => isNotificationsPageCacheKey(key)),
  ]);
}
