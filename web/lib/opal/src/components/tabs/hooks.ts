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
   usePillIndicator
   ============================================================================= */

export interface IndicatorStyle {
  left: number;
  width: number;
  opacity: number;
}

/**
 * Tracks the position of the sliding underline indicator for pill/underline
 * variants. Uses MutationObserver to react to Radix's data-state changes and
 * ResizeObserver to react to tab width changes.
 */
export function usePillIndicator(
  listRef: React.RefObject<HTMLElement | null>,
  enabled: boolean,
  scrollContainerRef?: React.RefObject<HTMLElement | null>
): { style: IndicatorStyle; isScrolling: boolean } {
  const [style, setStyle] = useState<IndicatorStyle>({
    left: 0,
    width: 0,
    opacity: 0,
  });
  const [isScrolling, setIsScrolling] = useState(false);
  const scrollTimeoutRef = useRef<NodeJS.Timeout | null>(null);

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
          width: tabRect.width,
          opacity: 1,
        });
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

  return { style, isScrolling };
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
    setCanScrollLeft(scrollLeft > 0);
    setCanScrollRight(
      scrollLeft + clientWidth < scrollWidth - SCROLL_TOLERANCE_PX
    );
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
