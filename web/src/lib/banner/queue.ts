// Pure queue-building logic for the banner card, kept free of hooks and
// browser dependencies so it can be unit tested directly.

import {
  NotificationSeverity,
  NotificationType,
  type Notification,
} from "@/lib/notifications/interfaces";

export interface BannerQueueItem {
  notification: Notification;
  // Every collapsed same-type notification in this slot, most urgent first.
  ids: number[];
  // Same-type notifications collapsed into this slot; >1 renders aggregate copy.
  count: number;
}

function severityRank(notification: Notification): number {
  return Object.values(NotificationSeverity).indexOf(notification.severity);
}

// Loudest first, ties broken by most recent.
function byUrgency(a: Notification, b: Notification): number {
  return (
    severityRank(b) - severityRank(a) ||
    new Date(b.last_shown).getTime() - new Date(a.last_shown).getTime()
  );
}

// One slot per type, holding that type's most urgent notification plus every
// collapsed id; slots come out loudest-first via the sorted insertion.
export function buildBannerQueue(
  notifications: Notification[],
  isHidden: (notification: Notification) => boolean
): BannerQueueItem[] {
  const byType = new Map<NotificationType, BannerQueueItem>();
  for (const notification of notifications
    .filter((n) => !isHidden(n))
    .sort(byUrgency)) {
    const slot = byType.get(notification.notif_type);
    if (slot) {
      slot.ids.push(notification.id);
      slot.count += 1;
    } else {
      byType.set(notification.notif_type, {
        notification,
        ids: [notification.id],
        count: 1,
      });
    }
  }
  return Array.from(byType.values());
}
