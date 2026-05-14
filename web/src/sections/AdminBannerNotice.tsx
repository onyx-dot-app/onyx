"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname } from "next/navigation";
import useSWR from "swr";
import { MessageCard } from "@opal/components";

import { errorHandlingFetcher } from "@/lib/fetcher";
import { Notification, NotificationType } from "@/lib/notifications/interfaces";
import { SWR_KEYS } from "@/lib/swr-keys";

const DISMISS_STORAGE_KEY = "admin-banner-dismissed";

function dismissKey(notificationId: number): string {
  return `${DISMISS_STORAGE_KEY}:${notificationId}`;
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

export default function AdminBannerNotice() {
  const { data } = useSWR<Notification[]>(
    SWR_KEYS.notifications,
    errorHandlingFetcher
  );
  const { left, width } = useMainContainerOffset();
  const [dismissedId, setDismissedId] = useState<number | null>(null);

  const banner = useMemo(() => {
    return (data ?? []).find(
      (n) => n.notif_type === NotificationType.ADMIN_BANNER && !n.dismissed
    );
  }, [data]);

  useEffect(() => {
    if (typeof window === "undefined" || !banner) {
      setDismissedId(null);
      return;
    }
    const isDismissed =
      window.localStorage.getItem(dismissKey(banner.id)) === "1";
    setDismissedId(isDismissed ? banner.id : null);
  }, [banner?.id]);

  if (!banner || dismissedId === banner.id) {
    return null;
  }

  async function handleDismiss() {
    if (!banner) return;
    if (typeof window !== "undefined") {
      window.localStorage.setItem(dismissKey(banner.id), "1");
    }
    setDismissedId(banner.id);
    try {
      await fetch(`/api/notifications/${banner.id}/dismiss`, {
        method: "POST",
      });
    } catch {
      // server-side dismiss is best-effort; localStorage already hides it
    }
  }

  return (
    <div
      className="fixed top-3 z-toast flex justify-center px-3 pointer-events-none"
      style={{ left, width: width || undefined }}
    >
      <div className="w-full max-w-3xl pointer-events-auto">
        <MessageCard
          variant="info"
          title={banner.title}
          description={banner.description ?? undefined}
          onClose={handleDismiss}
        />
      </div>
    </div>
  );
}
