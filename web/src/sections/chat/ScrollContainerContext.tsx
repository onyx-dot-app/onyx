"use client";

import React, {
  createContext,
  useContext,
  useMemo,
  RefObject,
  MutableRefObject,
} from "react";

/** How far beyond the viewport, above and below, a row stays mounted. */
const OVERSCAN_VIEWPORTS = 2;

interface ScrollContainerContextType {
  scrollContainerRef: RefObject<HTMLDivElement | null>;
  contentWrapperRef: RefObject<HTMLDivElement | null>;
  /** Shared ref for the DynamicBottomSpacer's current height (written by spacer, read by scroll container). */
  spacerHeightRef: MutableRefObject<number>;
  /**
   * Reports whether `target` is within `OVERSCAN_VIEWPORTS` viewport heights
   * of the scroll container, above or below. Returns a function that stops
   * observing. Call it after the container mounts.
   */
  observeNearViewport: (
    target: Element,
    onChange: (near: boolean) => void
  ) => () => void;
}

const ScrollContainerContext = createContext<
  ScrollContainerContextType | undefined
>(undefined);

export function ScrollContainerProvider({
  children,
  scrollContainerRef,
  contentWrapperRef,
  spacerHeightRef,
}: {
  children: React.ReactNode;
  scrollContainerRef: RefObject<HTMLDivElement | null>;
  contentWrapperRef: RefObject<HTMLDivElement | null>;
  spacerHeightRef: MutableRefObject<number>;
}) {
  // One observer for every row of the container, rebuilt only when the
  // container's height changes the margin.
  const observeNearViewport = useMemo(() => {
    const listeners = new Map<Element, (near: boolean) => void>();
    let observers: {
      intersection: IntersectionObserver;
      resize: ResizeObserver;
    } | null = null;
    const watch = (root: HTMLElement) =>
      new IntersectionObserver(
        (entries) => {
          for (const entry of entries)
            listeners.get(entry.target)?.(entry.isIntersecting);
        },
        // In pixels, because browsers do not agree on what a percentage of the
        // root is.
        {
          root,
          rootMargin: `${root.clientHeight * OVERSCAN_VIEWPORTS}px 0px`,
        }
      );
    return (target: Element, onChange: (near: boolean) => void) => {
      const root = scrollContainerRef.current;
      if (!root) return () => {};
      listeners.set(target, onChange);
      if (observers) {
        observers.intersection.observe(target);
      } else {
        let height = root.clientHeight;
        const current = {
          intersection: watch(root),
          resize: new ResizeObserver(() => {
            if (root.clientHeight === height) return;
            height = root.clientHeight;
            current.intersection.disconnect();
            current.intersection = watch(root);
            for (const listened of listeners.keys())
              current.intersection.observe(listened);
          }),
        };
        current.intersection.observe(target);
        current.resize.observe(root);
        observers = current;
      }
      return () => {
        listeners.delete(target);
        observers?.intersection.unobserve(target);
        if (listeners.size === 0) {
          observers?.intersection.disconnect();
          observers?.resize.disconnect();
          observers = null;
        }
      };
    };
  }, [scrollContainerRef]);
  // Memoize context value to prevent unnecessary re-renders of consumers.
  // The refs themselves are stable, but without memoization, a new object
  // would be created on every parent re-render.
  const value = useMemo(
    () => ({
      scrollContainerRef,
      contentWrapperRef,
      spacerHeightRef,
      observeNearViewport,
    }),
    [
      scrollContainerRef,
      contentWrapperRef,
      spacerHeightRef,
      observeNearViewport,
    ]
  );

  return (
    <ScrollContainerContext.Provider value={value}>
      {children}
    </ScrollContainerContext.Provider>
  );
}

/** Like `useScrollContainer`, but `undefined` outside a ScrollContainerProvider. */
export function useOptionalScrollContainer() {
  return useContext(ScrollContainerContext);
}

/**
 * Hook to access the scroll container and content wrapper refs.
 * Must be used within a ScrollContainerProvider (inside ChatScrollContainer).
 */
export function useScrollContainer() {
  const context = useContext(ScrollContainerContext);
  if (context === undefined) {
    throw new Error(
      "useScrollContainer must be used within a ScrollContainerProvider"
    );
  }
  return context;
}
