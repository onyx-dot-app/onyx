"use client";

// Bottom-left banner queue: consolidates every banner-worthy notification
// into a single pageable card, most urgent first.
//
// Banner-worthiness is severity-driven: one server-filtered fetch returns all
// of the user's WARNING-and-up notifications, so a new loud notification type
// needs no frontend changes. TRIAL_ENDS_TWO_DAYS is the one exception — it is
// a global (user=None) product-gating alert, so it rides in on the settings
// payload rather than the per-user feed, which only returns the caller's own
// rows.
//
// TODO(nikg): deliver `show_as_popup` to a first-visit popup renderer. The
// notification feed's `additional_data` is `{}` for SYSTEM_ANNOUNCEMENT
// (see backend `ensure_system_announcement_notification`), so the frontend
// currently has no way to know whether the admin's banner should also show
// a one-time popup. Needs a backend change to carry that flag through.

import { useCallback, useMemo, useState } from "react";
import { usePathname } from "next/navigation";
import useSWR, { mutate } from "swr";
import Cookies from "js-cookie";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { isAuthPath } from "@/lib/auth/paths";
import { useSettings } from "@/lib/settings/hooks";
import {
  dismissNotification,
  invalidateNotificationCaches,
} from "@/lib/notifications/api";
import {
  NotificationSeverity,
  NotificationType,
  type Notification,
  type NotificationsResponse,
} from "@/lib/notifications/interfaces";
import { buildBannerQueue, type BannerQueueItem } from "@/lib/banner/queue";

export type { BannerQueueItem } from "@/lib/banner/queue";

// A single max-size page always holds every active banner-worthy notification
// (only a handful are ever live per user at once).
const BANNER_NOTIFICATIONS_PAGE_SIZE = 50;

// Focus revalidation so a freshly published announcement reaches other open
// sessions without a reload, plus a slow poll so an idle admin tab still
// learns about a newly failing connector (the dedupe window caps the rate).
const BANNER_SWR_OPTIONS = {
  revalidateOnFocus: true,
  dedupingInterval: 30000,
  refreshInterval: 60000,
} as const;

const BANNER_NOTIFICATIONS_KEY = SWR_KEYS.notificationsBySeverity(
  NotificationSeverity.WARNING,
  BANNER_NOTIFICATIONS_PAGE_SIZE
);

// TRIAL_ENDS_TWO_DAYS is a global product-gating notification. It can only be
// dismissed per-user through a browser cookie: a basic user can't dismiss a
// global row server-side, and an admin dismiss would hide it tenant-wide. This
// mirrors the retired AnnouncementBanner.
const DISMISSED_NOTIFICATION_COOKIE_PREFIX = "dismissed_notification_";
const COOKIE_DISMISS_EXPIRY_DAYS = 1;

function isGlobalBannerType(notifType: NotificationType): boolean {
  return notifType === NotificationType.TRIAL_ENDS_TWO_DAYS;
}

export interface UseBannerQueueResult {
  current: BannerQueueItem | null;
  queueLength: number;
  hasMultiple: boolean;
  goToNext: () => void;
  goToPrevious: () => void;
  // Dismisses the current slot's representative, or the given ids (the card
  // passes every collapsed id when it rendered aggregate copy).
  dismissCurrent: (ids?: number[]) => Promise<void>;
}

export function useBannerQueue(): UseBannerQueueResult {
  const pathname = usePathname();
  // Unauthenticated /auth/* routes 403 on the notifications feed, so gate every
  // banner fetch (see isAuthPath's doc comment).
  const disabled = isAuthPath(pathname);

  // One severity-filtered fetch covers every banner-worthy notification type.
  const bannerWorthy = useSWR<NotificationsResponse>(
    disabled ? null : BANNER_NOTIFICATIONS_KEY,
    errorHandlingFetcher,
    BANNER_SWR_OPTIONS
  );
  // The global trial-ending alert arrives via the settings payload (see the
  // file header), not the per-user notifications feed.
  const settings = useSettings();

  const [index, setIndex] = useState(0);
  // IDs hidden optimistically while a server dismissal is in flight.
  const [pendingDismissals, setPendingDismissals] = useState<Set<number>>(
    new Set()
  );

  const notifications = useMemo<Notification[]>(
    () => [
      ...(bannerWorthy.data?.notifications ?? []),
      ...settings.notifications.filter(
        (n) => n.notif_type === NotificationType.TRIAL_ENDS_TWO_DAYS
      ),
    ],
    [bannerWorthy.data, settings.notifications]
  );

  // Dismissals must update every notification surface (this queue, the bell
  // popover, the badge, and the settings-sourced trial alert), so refresh goes
  // through the shared invalidation plus the settings cache.
  const refresh = useCallback(async () => {
    await invalidateNotificationCaches();
    await mutate(SWR_KEYS.settings);
  }, []);

  const queue = useMemo<BannerQueueItem[]>(() => {
    const dismissedCookies = Cookies.get();
    return buildBannerQueue(
      notifications,
      (n) =>
        n.dismissed ||
        pendingDismissals.has(n.id) ||
        `${DISMISSED_NOTIFICATION_COOKIE_PREFIX}${n.id}` in dismissedCookies
    );
  }, [notifications, pendingDismissals]);

  // Clamp during render, not in an effect. Dismissing a non-first banner
  // shrinks the queue on the same commit, and an effect-based clamp would leave
  // `current` undefined for one frame, flashing the whole card out and back in.
  // The paging setters already wrap with the same modulo, so a stale index is
  // always resolved to a valid slot here.
  const safeIndex = queue.length === 0 ? 0 : index % queue.length;
  const current = queue[safeIndex] ?? null;

  const goToNext = useCallback(() => {
    setIndex((i) => (queue.length === 0 ? 0 : (i + 1) % queue.length));
  }, [queue.length]);

  const goToPrevious = useCallback(() => {
    setIndex((i) =>
      queue.length === 0 ? 0 : (i - 1 + queue.length) % queue.length
    );
  }, [queue.length]);

  const dismissCurrent = useCallback(
    async (ids?: number[]) => {
      if (!current) return;
      const targets = ids ?? [current.notification.id];
      const global = isGlobalBannerType(current.notification.notif_type);
      setPendingDismissals((prev) => {
        const next = new Set(prev);
        targets.forEach((id) => next.add(id));
        return next;
      });
      // A global product-gating alert can't be dismissed per-user server-side,
      // so record the dismissal in a cookie and treat the server call as
      // best-effort.
      if (global) {
        for (const id of targets) {
          Cookies.set(`${DISMISSED_NOTIFICATION_COOKIE_PREFIX}${id}`, "true", {
            expires: COOKIE_DISMISS_EXPIRY_DAYS,
          });
        }
      }
      // Settle individually: a partial failure must not unhide targets that
      // did dismiss, and the refresh reconciles with server state either way.
      const results = await Promise.allSettled(
        targets.map(dismissNotification)
      );
      const failures = targets.flatMap((id, index) => {
        const result = results[index];
        return result?.status === "rejected"
          ? [{ id, reason: result.reason }]
          : [];
      });
      if (failures.length > 0 && !global) {
        console.error("Failed to dismiss banner notifications:", failures);
        setPendingDismissals((prev) => {
          const next = new Set(prev);
          failures.forEach(({ id }) => next.delete(id));
          return next;
        });
      }
      await refresh();
    },
    [current, refresh]
  );

  return {
    current,
    queueLength: queue.length,
    hasMultiple: queue.length > 1,
    goToNext,
    goToPrevious,
    dismissCurrent,
  };
}
