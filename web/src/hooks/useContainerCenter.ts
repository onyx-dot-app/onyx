"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";

const SELECTOR = "[data-main-container]";

interface ContainerCenter {
  centerX: number | null;
  centerY: number | null;
  hasContainerCenter: boolean;
}

const NULL_CENTER = { x: null, y: null } as const;

function measure(el: HTMLElement): { x: number; y: number } | null {
  if (!el.isConnected) return null;
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return null;
  return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
}

/**
 * Tracks the center point of the `[data-main-container]` element so that
 * portaled overlays (modals, command menus) can center relative to the main
 * content area rather than the full viewport.
 *
 * Returns `{ centerX, centerY, hasContainerCenter }`.
 * When the container is not present (e.g. pages without `AppLayouts.Root`),
 * both center values are `null` and `hasContainerCenter` is `false`, allowing
 * callers to fall back to standard viewport centering.
 *
 * Uses a lazy `useState` initializer so the first render already has the
 * correct values (no flash), and a `ResizeObserver` to stay reactive when
 * the sidebar folds/unfolds. Re-subscribes on route changes because each
 * page renders its own `AppLayouts.Root`, replacing the DOM element.
 */
export default function useContainerCenter(): ContainerCenter {
  const pathname = usePathname();
  const [center, setCenter] = useState<{ x: number | null; y: number | null }>(
    () => {
      if (typeof document === "undefined") return NULL_CENTER;
      const el = document.querySelector<HTMLElement>(SELECTOR);
      if (!el) return NULL_CENTER;
      const m = measure(el);
      return m ?? NULL_CENTER;
    }
  );

  useEffect(() => {
    const container = document.querySelector<HTMLElement>(SELECTOR);
    if (!container) {
      setCenter(NULL_CENTER);
      return;
    }

    const update = () => {
      const m = measure(container);
      setCenter(m ?? NULL_CENTER);
    };

    update();
    const observer = new ResizeObserver(update);
    observer.observe(container);
    return () => observer.disconnect();
  }, [pathname]);

  return {
    centerX: center.x,
    centerY: center.y,
    hasContainerCenter: center.x !== null && center.y !== null,
  };
}
