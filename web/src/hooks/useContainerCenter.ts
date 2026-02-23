"use client";

import { useState, useEffect } from "react";

const SELECTOR = "[data-main-container]";

interface ContainerCenter {
  centerX: number | null;
  centerY: number | null;
  hasContainerCenter: boolean;
}

function measure(el: HTMLElement): { x: number; y: number } {
  const rect = el.getBoundingClientRect();
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
 * the sidebar folds/unfolds.
 */
export default function useContainerCenter(): ContainerCenter {
  const [center, setCenter] = useState<{ x: number | null; y: number | null }>(
    () => {
      if (typeof document === "undefined") return { x: null, y: null };
      const el = document.querySelector<HTMLElement>(SELECTOR);
      if (!el) return { x: null, y: null };
      const m = measure(el);
      return { x: m.x, y: m.y };
    }
  );

  useEffect(() => {
    const container = document.querySelector<HTMLElement>(SELECTOR);
    if (!container) return;

    const update = () => {
      const m = measure(container);
      setCenter({ x: m.x, y: m.y });
    };

    update();
    const observer = new ResizeObserver(update);
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  return {
    centerX: center.x,
    centerY: center.y,
    hasContainerCenter: center.x !== null && center.y !== null,
  };
}
