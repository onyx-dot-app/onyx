"use client";

import React, {
  createContext,
  useContext,
  useMemo,
  RefObject,
  MutableRefObject,
} from "react";

interface ScrollContainerContextType {
  scrollContainerRef: RefObject<HTMLDivElement | null>;
  contentWrapperRef: RefObject<HTMLDivElement | null>;
  /** Shared ref for the DynamicBottomSpacer's current height (written by spacer, read by scroll container). */
  spacerHeightRef: MutableRefObject<number>;
  /** True iff the user has manually scrolled up since the last bottom-anchored scroll. Updated only by handleScroll's scrolled-up detection (no flaky layout math). Read by DynamicBottomSpacer to gate hoist behavior. */
  userScrolledUpRef: MutableRefObject<boolean>;
}

const ScrollContainerContext = createContext<
  ScrollContainerContextType | undefined
>(undefined);

export function ScrollContainerProvider({
  children,
  scrollContainerRef,
  contentWrapperRef,
  spacerHeightRef,
  userScrolledUpRef,
}: {
  children: React.ReactNode;
  scrollContainerRef: RefObject<HTMLDivElement | null>;
  contentWrapperRef: RefObject<HTMLDivElement | null>;
  spacerHeightRef: MutableRefObject<number>;
  userScrolledUpRef: MutableRefObject<boolean>;
}) {
  // Memoize context value to prevent unnecessary re-renders of consumers.
  // The refs themselves are stable, but without memoization, a new object
  // would be created on every parent re-render.
  const value = useMemo(
    () => ({
      scrollContainerRef,
      contentWrapperRef,
      spacerHeightRef,
      userScrolledUpRef,
    }),
    [scrollContainerRef, contentWrapperRef, spacerHeightRef, userScrolledUpRef]
  );

  return (
    <ScrollContainerContext.Provider value={value}>
      {children}
    </ScrollContainerContext.Provider>
  );
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
