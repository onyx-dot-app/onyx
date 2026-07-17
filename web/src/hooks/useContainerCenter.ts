"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import useScreenSize from "@/hooks/useScreenSize";

const SELECTOR = "[data-main-container]";

interface ContainerCenter {
  centerX: number | null;
  centerY: number | null;
  /** Viewport x of the container's left edge (the sidebar/content boundary). */
  left: number | null;
  hasContainerCenter: boolean;
}

const NULL_MEASURE = { x: null, y: null, left: null } as const;

function measure(
  el: HTMLElement
): { x: number; y: number; left: number } | null {
  if (!el.isConnected) return null;
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return null;
  return {
    x: rect.left + rect.width / 2,
    y: rect.top + rect.height / 2,
    left: rect.left,
  };
}

/**
 * Tracks the geometry of the `[data-main-container]` element so overlays can
 * position relative to the main content area rather than the full viewport:
 * `centerX`/`centerY` for portaled modals and command menus, `left` for
 * content-anchored surfaces like the bottom-left banner queue.
 *
 * When the container is absent (pages without `AppLayouts.Root`) or the
 * sidebar overlays the content on medium screens, every value is `null` and
 * `hasContainerCenter` is `false`, so callers fall back to viewport-relative
 * positioning.
 *
 * Uses a lazy `useState` initializer so the first render already has the
 * correct values (no flash), and a `ResizeObserver` to stay reactive when
 * the sidebar folds/unfolds. Re-subscribes on route changes because each
 * page renders its own `AppLayouts.Root`, replacing the DOM element.
 */
export default function useContainerCenter(): ContainerCenter {
  const pathname = usePathname();
  const { isMediumScreen } = useScreenSize();
  const [rect, setRect] = useState<{
    x: number | null;
    y: number | null;
    left: number | null;
  }>(() => {
    if (typeof document === "undefined") return NULL_MEASURE;
    const el = document.querySelector<HTMLElement>(SELECTOR);
    if (!el) return NULL_MEASURE;
    const m = measure(el);
    return m ?? NULL_MEASURE;
  });

  useEffect(() => {
    let resizeObserver: ResizeObserver | null = null;
    let mutationObserver: MutationObserver | null = null;

    const attach = (container: HTMLElement) => {
      const update = () => setRect(measure(container) ?? NULL_MEASURE);
      update();
      resizeObserver = new ResizeObserver(update);
      resizeObserver.observe(container);
    };

    const existing = document.querySelector<HTMLElement>(SELECTOR);
    if (existing) {
      attach(existing);
    } else {
      // The container can mount after this hook (e.g. a root-level consumer
      // renders before the auth shell reveals the chrome). Watch for it.
      setRect(NULL_MEASURE);
      mutationObserver = new MutationObserver(() => {
        const el = document.querySelector<HTMLElement>(SELECTOR);
        if (!el) return;
        mutationObserver?.disconnect();
        mutationObserver = null;
        attach(el);
      });
      mutationObserver.observe(document.body, {
        childList: true,
        subtree: true,
      });
    }

    return () => {
      resizeObserver?.disconnect();
      mutationObserver?.disconnect();
    };
  }, [pathname]);

  return {
    centerX: isMediumScreen ? null : rect.x,
    centerY: isMediumScreen ? null : rect.y,
    left: isMediumScreen ? null : rect.left,
    hasContainerCenter: isMediumScreen
      ? false
      : rect.x !== null && rect.y !== null,
  };
}
