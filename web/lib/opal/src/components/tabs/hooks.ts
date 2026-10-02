"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";

/* =============================================================================
   CONTEXT
   ============================================================================= */

export interface TabsContextValue {
  variant: "contained" | "pill" | "underline";
}

export const TabsContext = React.createContext<TabsContextValue | undefined>(
  undefined
);

export function useTabsContext(): TabsContextValue | undefined {
  return React.useContext(TabsContext);
}

/* =============================================================================
   useTabIndicator
   ============================================================================= */

/** The active tab's box, relative to the list. */
export interface IndicatorStyle {
  left: number;
  top: number;
  width: number;
  height: number;
  opacity: number;
}

/**
 * Tracks the active tab's box so the list's sliding indicators (every
 * variant's active surface, and the pill/underline bar) can move to it. Uses
 * MutationObserver to react to Radix's data-state changes and ResizeObserver
 * to react to tab size changes.
 *
 * `measured` turns true once the first position is known, so the indicators
 * can hold their transition until then and not sweep in from the edge.
 */
export function useTabIndicator(
  listRef: React.RefObject<HTMLElement | null>,
  enabled: boolean,
  scrollContainerRef?: React.RefObject<HTMLElement | null>
): { style: IndicatorStyle; isScrolling: boolean; measured: boolean } {
  const [style, setStyle] = useState<IndicatorStyle>({
    left: 0,
    top: 0,
    width: 0,
    height: 0,
    opacity: 0,
  });
  const [measured, setMeasured] = useState(false);
  const [isScrolling, setIsScrolling] = useState(false);
  const scrollTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // The scroll-debounce timer is ref-held and cleared in this effect's
  // cleanup. The rule cannot trace handler-created timers.
  // oxlint-disable-next-line react-doctor/effect-needs-cleanup
  useEffect(() => {
    if (!enabled) return;

    const list = listRef.current;
    if (!list) return;

    const updateIndicator = () => {
      const activeTab = list.querySelector<HTMLElement>(
        '[data-state="active"]'
      );
      if (activeTab) {
        const listRect = list.getBoundingClientRect();
        const tabRect = activeTab.getBoundingClientRect();
        setStyle({
          left: tabRect.left - listRect.left,
          top: tabRect.top - listRect.top,
          width: tabRect.width,
          height: tabRect.height,
          opacity: 1,
        });
        // A frame later, so the first position lands without a transition.
        requestAnimationFrame(() => setMeasured(true));
      }
    };

    const handleScroll = () => {
      setIsScrolling(true);
      updateIndicator();
      if (scrollTimeoutRef.current) clearTimeout(scrollTimeoutRef.current);
      scrollTimeoutRef.current = setTimeout(() => setIsScrolling(false), 150);
    };

    updateIndicator();

    const resizeObserver = new ResizeObserver(() => updateIndicator());
    resizeObserver.observe(list);
    list.querySelectorAll<HTMLElement>('[role="tab"]').forEach((tab) => {
      resizeObserver.observe(tab);
    });

    const mutationObserver = new MutationObserver((mutations) => {
      updateIndicator();
      for (const mutation of mutations) {
        for (const node of Array.from(mutation.addedNodes)) {
          if (node instanceof HTMLElement) resizeObserver.observe(node);
        }
      }
    });
    mutationObserver.observe(list, {
      attributes: true,
      childList: true,
      subtree: true,
      attributeFilter: ["data-state"],
    });

    const scrollContainer = scrollContainerRef?.current;
    if (scrollContainer) {
      scrollContainer.addEventListener("scroll", handleScroll);
    }

    return () => {
      mutationObserver.disconnect();
      resizeObserver.disconnect();
      if (scrollContainer)
        scrollContainer.removeEventListener("scroll", handleScroll);
      if (scrollTimeoutRef.current) clearTimeout(scrollTimeoutRef.current);
    };
  }, [enabled, listRef, scrollContainerRef]);

  return { style, isScrolling, measured };
}

/* =============================================================================
   useHorizontalScroll
   ============================================================================= */

export interface ScrollState {
  canScrollLeft: boolean;
  canScrollRight: boolean;
  scrollLeft: () => void;
  scrollRight: () => void;
}

const SCROLL_TOLERANCE_PX = 1;
const SCROLL_AMOUNT_PX = 200;

/**
 * Tracks horizontal overflow state of a container and exposes scroll helpers
 * used by the optional scroll-arrow controls in TabsList.
 */
export function useHorizontalScroll(
  containerRef: React.RefObject<HTMLElement | null>,
  enabled: boolean
): ScrollState {
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  const updateScrollState = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const { scrollLeft, scrollWidth, clientWidth } = container;
    // RTL scrollers run scrollLeft from 0 down to negative values, so
    // normalize to distance from the physical left edge. The arrows and
    // scrollBy already speak physical directions.
    const maxScroll = scrollWidth - clientWidth;
    const fromLeft =
      getComputedStyle(container).direction === "rtl"
        ? maxScroll + scrollLeft
        : scrollLeft;
    setCanScrollLeft(fromLeft > 0);
    setCanScrollRight(fromLeft < maxScroll - SCROLL_TOLERANCE_PX);
  }, [containerRef]);

  useEffect(() => {
    if (!enabled) return;
    const container = containerRef.current;
    if (!container) return;

    const rafId = requestAnimationFrame(updateScrollState);
    container.addEventListener("scroll", updateScrollState);
    const resizeObserver = new ResizeObserver(updateScrollState);
    resizeObserver.observe(container);
    Array.from(container.children).forEach((child) =>
      resizeObserver.observe(child)
    );
    const mutationObserver = new MutationObserver((mutations) => {
      updateScrollState();
      for (const mutation of mutations) {
        for (const node of Array.from(mutation.addedNodes)) {
          if (node instanceof HTMLElement) resizeObserver.observe(node);
        }
      }
    });
    mutationObserver.observe(container, { childList: true });

    return () => {
      cancelAnimationFrame(rafId);
      container.removeEventListener("scroll", updateScrollState);
      resizeObserver.disconnect();
      mutationObserver.disconnect();
    };
  }, [enabled, containerRef, updateScrollState]);

  const scrollLeft = useCallback(() => {
    containerRef.current?.scrollBy({
      left: -SCROLL_AMOUNT_PX,
      behavior: "smooth",
    });
  }, [containerRef]);

  const scrollRight = useCallback(() => {
    containerRef.current?.scrollBy({
      left: SCROLL_AMOUNT_PX,
      behavior: "smooth",
    });
  }, [containerRef]);

  return { canScrollLeft, canScrollRight, scrollLeft, scrollRight };
}
