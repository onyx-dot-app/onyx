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
  /** Shared ref tracking whether the user is at the bottom (written by ChatScrollContainer's scroll handler, read by descendants like DynamicBottomSpacer). Reflects the position BEFORE the most recent content mutation. */
  isAtBottomRef: MutableRefObject<boolean>;
  /** True iff the user has manually scrolled up since the last bottom-anchored scroll. Updated only by handleScroll's scrolled-up detection (no flaky layout math). Consumers (anchor effect, DynamicBottomSpacer) read this to gate hoist behavior. */
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
  isAtBottomRef,
  userScrolledUpRef,
}: {
  children: React.ReactNode;
  scrollContainerRef: RefObject<HTMLDivElement | null>;
  contentWrapperRef: RefObject<HTMLDivElement | null>;
  spacerHeightRef: MutableRefObject<number>;
  isAtBottomRef: MutableRefObject<boolean>;
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
      isAtBottomRef,
      userScrolledUpRef,
    }),
    [
      scrollContainerRef,
      contentWrapperRef,
      spacerHeightRef,
      isAtBottomRef,
      userScrolledUpRef,
    ]
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
