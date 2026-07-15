"use client";

// Bottom-left banner queue: consolidates the site-wide admin announcement and
// the other banner-worthy notification types (license expiry, trial ending)
// into a single pageable card, most urgent first.
//
// Per-user types (admin announcement, license expiry) each get their own
// type-filtered notifications request so none is paged out behind newer,
// unrelated items. TRIAL_ENDS_TWO_DAYS is a global (user=None) product-gating
// alert, so it rides in on the settings payload rather than the per-user feed,
// which only returns the caller's own rows.
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
  NotificationType,
  type Notification,
  type NotificationsResponse,
} from "@/lib/notifications/interfaces";
import type { ExpiryWarningStage } from "@/lib/billing/interfaces";

// A single max-size page always holds every active notification of a given
// banner-worthy type (only a handful are ever live per user at once).
const BANNER_NOTIFICATIONS_PAGE_SIZE = 50;

// Focus revalidation on so a freshly published announcement reaches other
// open sessions without a reload (the dedupe window caps the request rate).
const BANNER_SWR_OPTIONS = {
  revalidateOnFocus: true,
  dedupingInterval: 30000,
} as const;

// Types that render in the bottom-left banner queue, most urgent first.
const BANNER_TYPE_PRIORITY: Partial<Record<NotificationType, number>> = {
  [NotificationType.LICENSE_EXPIRY_WARNING]: 2,
  [NotificationType.TRIAL_ENDS_TWO_DAYS]: 1,
  [NotificationType.SYSTEM_ANNOUNCEMENT]: 0,
};

// Higher = more urgent.
const LICENSE_STAGE_SEVERITY: Record<
  Exclude<ExpiryWarningStage, "none">,
  number
> = {
  t_30d: 0,
  t_14d: 1,
  t_1d: 2,
  grace: 3,
};

function severityForLicenseStage(stage: string | undefined): number {
  return (LICENSE_STAGE_SEVERITY as Record<string, number>)[stage ?? ""] ?? 0;
}

/** Severity rank for a LICENSE_EXPIRY_WARNING notification's stage (higher = more urgent). */
export function licenseExpirySeverity(notification: Notification): number {
  return severityForLicenseStage(notification.additional_data?.stage);
}

// t_1d and grace (and anything more urgent) render as an error.
export const LICENSE_EXPIRY_ERROR_THRESHOLD = LICENSE_STAGE_SEVERITY.t_1d;

function isBannerWorthy(notification: Notification): boolean {
  return notification.notif_type in BANNER_TYPE_PRIORITY;
}

// TRIAL_ENDS_TWO_DAYS is a global product-gating notification. It can only be
// dismissed per-user through a browser cookie: a basic user can't dismiss a
// global row server-side, and an admin dismiss would hide it tenant-wide. This
// mirrors the retired AnnouncementBanner.
const DISMISSED_NOTIFICATION_COOKIE_PREFIX = "dismissed_notification_";
const COOKIE_DISMISS_EXPIRY_DAYS = 1;

function isGlobalBannerType(notifType: NotificationType): boolean {
  return notifType === NotificationType.TRIAL_ENDS_TWO_DAYS;
}

function isCookieDismissed(id: number): boolean {
  return Boolean(Cookies.get(`${DISMISSED_NOTIFICATION_COOKIE_PREFIX}${id}`));
}

// Collapses multiple undismissed notifications of the same banner type into the
// single one that should occupy that type's queue slot: most severe stage for
// license warnings (ties broken by most recent), most recent for everything else.
function pickRepresentative(
  notifType: NotificationType,
  candidates: Notification[]
): Notification {
  if (notifType !== NotificationType.LICENSE_EXPIRY_WARNING) {
    return candidates.reduce((latest, n) =>
      new Date(n.last_shown).getTime() > new Date(latest.last_shown).getTime()
        ? n
        : latest
    );
  }
  return candidates.reduce((best, n) => {
    const nextSeverity = licenseExpirySeverity(n);
    const bestSeverity = licenseExpirySeverity(best);
    if (nextSeverity > bestSeverity) return n;
    if (
      nextSeverity === bestSeverity &&
      new Date(n.last_shown).getTime() > new Date(best.last_shown).getTime()
    ) {
      return n;
    }
    return best;
  });
}

export interface UseBannerQueueResult {
  current: Notification | null;
  queueLength: number;
  hasMultiple: boolean;
  goToNext: () => void;
  goToPrevious: () => void;
  dismissCurrent: () => Promise<void>;
}

export function useBannerQueue(): UseBannerQueueResult {
  const pathname = usePathname();
  // Unauthenticated /auth/* routes 403 on the notifications feed, so gate every
  // banner fetch (see isAuthPath's doc comment).
  const disabled = isAuthPath(pathname);

  // One type-filtered fetch per banner type guarantees full coverage of each
  // type independent of how many unrelated notifications exist.
  const announcement = useSWR<NotificationsResponse>(
    disabled
      ? null
      : SWR_KEYS.notificationsByType(
          NotificationType.SYSTEM_ANNOUNCEMENT,
          BANNER_NOTIFICATIONS_PAGE_SIZE
        ),
    errorHandlingFetcher,
    BANNER_SWR_OPTIONS
  );
  const license = useSWR<NotificationsResponse>(
    disabled
      ? null
      : SWR_KEYS.notificationsByType(
          NotificationType.LICENSE_EXPIRY_WARNING,
          BANNER_NOTIFICATIONS_PAGE_SIZE
        ),
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
      ...(announcement.data?.notifications ?? []),
      ...(license.data?.notifications ?? []),
      ...settings.notifications.filter(
        (n) => n.notif_type === NotificationType.TRIAL_ENDS_TWO_DAYS
      ),
    ],
    [announcement.data, license.data, settings.notifications]
  );

  // Dismissals must update every notification surface (this queue, the bell
  // popover, the badge, and the settings-sourced trial alert), so refresh goes
  // through the shared invalidation plus the settings cache.
  const refresh = useCallback(async () => {
    await invalidateNotificationCaches();
    await mutate(SWR_KEYS.settings);
  }, []);

  const queue = useMemo(() => {
    const byType = new Map<NotificationType, Notification[]>();
    for (const notification of notifications) {
      if (
        !isBannerWorthy(notification) ||
        notification.dismissed ||
        pendingDismissals.has(notification.id) ||
        isCookieDismissed(notification.id)
      ) {
        continue;
      }
      const bucket = byType.get(notification.notif_type) ?? [];
      bucket.push(notification);
      byType.set(notification.notif_type, bucket);
    }

    return Array.from(byType.entries())
      .map(([notifType, candidates]) =>
        pickRepresentative(notifType, candidates)
      )
      .sort(
        (a, b) =>
          (BANNER_TYPE_PRIORITY[b.notif_type] ?? -1) -
          (BANNER_TYPE_PRIORITY[a.notif_type] ?? -1)
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

  const dismissCurrent = useCallback(async () => {
    if (!current) return;
    const id = current.id;
    const global = isGlobalBannerType(current.notif_type);
    setPendingDismissals((prev) => new Set(prev).add(id));
    // A global product-gating alert can't be dismissed per-user server-side, so
    // record the dismissal in a cookie and treat the server call as best-effort.
    if (global) {
      Cookies.set(`${DISMISSED_NOTIFICATION_COOKIE_PREFIX}${id}`, "true", {
        expires: COOKIE_DISMISS_EXPIRY_DAYS,
      });
    }
    try {
      await dismissNotification(id);
    } catch (error) {
      if (!global) {
        console.error("Failed to dismiss banner notification:", error);
        setPendingDismissals((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
        return;
      }
    }
    await refresh();
  }, [current, refresh]);

  return {
    current,
    queueLength: queue.length,
    hasMultiple: queue.length > 1,
    goToNext,
    goToPrevious,
    dismissCurrent,
  };
}
