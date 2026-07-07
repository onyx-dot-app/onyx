"use client";

// Floating banner for self-hosted license expiry. Renders the most urgent
// undismissed LICENSE_EXPIRY_WARNING notification and dismisses through the
// notifications API, so a dismissal persists per-user server-side and survives
// browser/localStorage resets. Notifications are created per stage (admins
// only, single-tenant) by the license-expiry Celery task. Fetches the
// notifications feed filtered to this type so the warning can't be paged out
// behind unrelated notifications.

import { useEffect, useMemo, useState } from "react";
import { usePathname } from "next/navigation";
import useSWR from "swr";
import { MessageCard } from "@opal/components";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { dismissNotification } from "@/lib/notifications/api";
import {
  NotificationType,
  type Notification,
  type NotificationsResponse,
} from "@/lib/notifications/interfaces";
import type { ExpiryWarningStage } from "@/lib/billing/interfaces";

// Per-user license notifications are few (one per active stage, plus a daily
// one during grace), so a single max-size page always contains them all.
const LICENSE_NOTIFICATIONS_PAGE_SIZE = 50;

// Single source for stage semantics (higher = more urgent): picks which warning
// to show when several are undismissed and drives the banner variant. Typed
// against ExpiryWarningStage so a stage added to that union must be ranked here.
const STAGE_SEVERITY: Record<Exclude<ExpiryWarningStage, "none">, number> = {
  t_30d: 0,
  t_14d: 1,
  t_1d: 2,
  grace: 3,
};

// t_1d and grace (and anything more urgent) render as an error.
const ERROR_THRESHOLD = STAGE_SEVERITY.t_1d;

function severityForStage(stage: string | undefined): number {
  return (STAGE_SEVERITY as Record<string, number>)[stage ?? ""] ?? 0;
}

function useMainContainerOffset(): { left: number; width: number } {
  const pathname = usePathname();
  const [bounds, setBounds] = useState<{ left: number; width: number }>({
    left: 0,
    width: 0,
  });

  useEffect(() => {
    if (typeof window === "undefined") return;
    let target: HTMLElement | null = null;
    let frame = 0;

    function update() {
      const el = document.querySelector<HTMLElement>("[data-main-container]");
      if (el) {
        const rect = el.getBoundingClientRect();
        setBounds({ left: rect.left, width: rect.width });
        if (target !== el) {
          ro.disconnect();
          ro.observe(el);
          target = el;
        }
      } else {
        setBounds({ left: 0, width: window.innerWidth });
        target = null;
      }
    }

    const ro = new ResizeObserver(update);
    const mo = new MutationObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(update);
    });

    update();
    mo.observe(document.body, { childList: true, subtree: true });
    window.addEventListener("resize", update);

    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      mo.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [pathname]);

  return bounds;
}

export default function LicenseExpiryBanner() {
  const { data, mutate } = useSWR<NotificationsResponse>(
    SWR_KEYS.notificationsByType(
      NotificationType.LICENSE_EXPIRY_WARNING,
      LICENSE_NOTIFICATIONS_PAGE_SIZE
    ),
    errorHandlingFetcher,
    { revalidateOnFocus: false, dedupingInterval: 30000 }
  );
  const { left, width } = useMainContainerOffset();
  // IDs hidden optimistically while the server dismissal is in flight.
  const [pendingDismissals, setPendingDismissals] = useState<Set<number>>(
    new Set()
  );

  const active = useMemo<Notification | null>(() => {
    const candidates = (data?.notifications ?? []).filter(
      (notification) =>
        notification.notif_type === NotificationType.LICENSE_EXPIRY_WARNING &&
        !notification.dismissed &&
        !pendingDismissals.has(notification.id)
    );
    return candidates.reduce<Notification | null>((best, notification) => {
      if (!best) return notification;
      const next = severityForStage(notification.additional_data?.stage);
      const current = severityForStage(best.additional_data?.stage);
      if (next > current) return notification;
      // Same stage: keep the most recent. Compare instants, not raw strings.
      if (
        next === current &&
        new Date(notification.last_shown).getTime() >
          new Date(best.last_shown).getTime()
      ) {
        return notification;
      }
      return best;
    }, null);
  }, [data, pendingDismissals]);

  if (!active) return null;

  const activeId = active.id;
  const variant =
    severityForStage(active.additional_data?.stage) >= ERROR_THRESHOLD
      ? "error"
      : "warning";

  function handleDismiss() {
    // Hide immediately; persist server-side. Restore on failure so the warning
    // isn't silently lost and the user can retry.
    setPendingDismissals((prev) => new Set(prev).add(activeId));
    void dismissNotification(activeId)
      .then(() => mutate())
      .catch((error) => {
        console.error("Failed to dismiss license expiry notification:", error);
        setPendingDismissals((prev) => {
          const next = new Set(prev);
          next.delete(activeId);
          return next;
        });
      });
  }

  return (
    <div
      className="fixed top-3 z-toast flex justify-center px-3 pointer-events-none"
      style={{ left, width: width || undefined }}
    >
      <div className="w-full max-w-3xl pointer-events-auto">
        <MessageCard
          variant={variant}
          title={active.title}
          description={active.description ?? undefined}
          onClose={handleDismiss}
        />
      </div>
    </div>
  );
}
