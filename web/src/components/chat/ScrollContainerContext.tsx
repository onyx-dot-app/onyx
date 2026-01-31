"use client";

import React, { createContext, useContext, useMemo, RefObject } from "react";

interface ScrollContainerContextType {
  scrollContainerRef: RefObject<HTMLDivElement | null>;
  contentWrapperRef: RefObject<HTMLDivElement | null>;
}

const ScrollContainerContext = createContext<
  ScrollContainerContextType | undefined
>(undefined);

export function ScrollContainerProvider({
  children,
  scrollContainerRef,
  contentWrapperRef,
}: {
  children: React.ReactNode;
  scrollContainerRef: RefObject<HTMLDivElement | null>;
  contentWrapperRef: RefObject<HTMLDivElement | null>;
}) {
  // Memoize context value to prevent unnecessary re-renders of consumers.
  // The refs themselves are stable, but without memoization, a new object
  // would be created on every parent re-render.
  const value = useMemo(
    () => ({ scrollContainerRef, contentWrapperRef }),
    [scrollContainerRef, contentWrapperRef]
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
