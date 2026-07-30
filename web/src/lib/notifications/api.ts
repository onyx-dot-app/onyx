import { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";

/** Revalidate every notifications cache: the mixed feed (useSWRInfinite keys
 * serialize with a $inf$ prefix, so match by inclusion), the by-type variants,
 * and the summary badge. Call after any dismissal so every surface showing a
 * notification (bell popover, banner queue, badge) updates together. */
export function invalidateNotificationCaches(): Promise<unknown> {
  return mutate(
    (key) => typeof key === "string" && key.includes(SWR_KEYS.notifications)
  );
}

async function handleNotificationMutation(
  response: Response,
  fallbackMessage: string
): Promise<void> {
  if (response.ok) {
    return;
  }

  const error = await response.json().catch(() => ({}));
  throw new Error(error.detail || fallbackMessage);
}

export async function dismissNotification(
  notificationId: number
): Promise<void> {
  const response = await fetch(`/api/notifications/${notificationId}/dismiss`, {
    method: "POST",
  });
  return handleNotificationMutation(response, "Failed to dismiss notification");
}

export async function dismissAllNotifications(): Promise<void> {
  const response = await fetch("/api/notifications/dismiss-all", {
    method: "POST",
  });
  return handleNotificationMutation(
    response,
    "Failed to dismiss notifications"
  );
}
