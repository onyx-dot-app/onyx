"use client";

import { useState, useEffect } from "react";
import useScreenSize from "@/hooks/useScreenSize";

const SELECTOR = "[data-main-container]";

interface ContainerCenter {
  centerX: number | null;
  centerY: number | null;
  /** Viewport x of the container's left edge (the sidebar/content boundary). */
  left: number | null;
  /** Distance from the inline-start viewport edge, for logical positioning. */
  inlineStart: number | null;
  hasContainerCenter: boolean;
}

const NULL_MEASURE = {
  x: null,
  y: null,
  left: null,
  inlineStart: null,
} as const;

function measure(
  el: HTMLElement
): { x: number; y: number; left: number; inlineStart: number } | null {
  if (!el.isConnected) return null;
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return null;
  return {
    x: rect.left + rect.width / 2,
    y: rect.top + rect.height / 2,
    left: rect.left,
    // Distance from the inline-start viewport edge, for consumers that
    // position with logical properties.
    inlineStart:
      getComputedStyle(el).direction === "rtl"
        ? window.innerWidth - rect.right
        : rect.left,
  };
}

/**
 * Tracks the geometry of the `[data-main-container]` element so overlays can
 * position relative to the main content area rather than the full viewport:
 * `centerX`/`centerY` for portaled modals and command menus, `left` for
 * content-anchored surfaces like the bottom-left banner queue.
 *
 * When the container is absent (pages without `AppLayouts.Root`) or the
 * viewport is below the large-screen breakpoint — where the sidebar-inset
 * content area isn't wide enough to center a modal within — every value is
 * `null` and `hasContainerCenter` is `false`, so callers fall back to
 * viewport-relative positioning.
 *
 * Uses a lazy `useState` initializer so the first render already has the
 * correct values (no flash), and a `ResizeObserver` to stay reactive when
 * the sidebar folds/unfolds. Follows the element itself, because each chrome
 * renders its own container and a navigation replaces it after the URL moves.
 */
export default function useContainerCenter(): ContainerCenter {
  const { isMediumScreen } = useScreenSize();
  const [container, setContainer] = useState<HTMLElement | null>(() => {
    if (typeof document === "undefined") return null;
    return document.querySelector<HTMLElement>(SELECTOR);
  });
  const [rect, setRect] = useState<{
    x: number | null;
    y: number | null;
    left: number | null;
    inlineStart: number | null;
  }>(() => {
    if (typeof document === "undefined") return NULL_MEASURE;
    const el = document.querySelector<HTMLElement>(SELECTOR);
    if (!el) return NULL_MEASURE;
    const m = measure(el);
    return m ?? NULL_MEASURE;
  });

  useEffect(() => {
    let frame = 0;
    const sync = () => {
      frame = 0;
      const el = document.querySelector<HTMLElement>(SELECTOR);
      setContainer((current) => (current === el ? current : el));
      if (!el) setRect(NULL_MEASURE);
    };
    sync();
    // The container can mount after this hook (e.g. a root-level consumer
    // renders before the auth shell reveals the chrome), and a navigation to
    // another chrome replaces it. Check once per frame of DOM changes.
    const mutationObserver = new MutationObserver(() => {
      if (frame === 0) frame = requestAnimationFrame(sync);
    });
    mutationObserver.observe(document.body, {
      childList: true,
      subtree: true,
    });

    return () => {
      mutationObserver.disconnect();
      cancelAnimationFrame(frame);
    };
  }, []);

  useEffect(() => {
    if (!container) return;

    const update = () => setRect(measure(container) ?? NULL_MEASURE);
    update();

    const resizeObserver = new ResizeObserver(update);
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
    };
  }, [container]);

  return {
    centerX: isMediumScreen ? null : rect.x,
    centerY: isMediumScreen ? null : rect.y,
    left: isMediumScreen ? null : rect.left,
    inlineStart: isMediumScreen ? null : rect.inlineStart,
    hasContainerCenter: isMediumScreen
      ? false
      : rect.x !== null && rect.y !== null,
  };
}
