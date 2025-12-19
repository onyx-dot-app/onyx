"use client";

import React, { useRef, useEffect, useLayoutEffect } from "react";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

export interface VerticalShadowScrollerProps
  extends React.HtmlHTMLAttributes<HTMLDivElement> {
  // Mask related
  disableMask?: boolean;
  backgroundColor?: string;
  height?: string;
  /**
   * Unique identifier for this scroll container to enable scroll position persistence across navigation.
   *
   * When provided, the scroll position will be saved to a global Map and restored when the pathname changes
   * (e.g., navigating between admin pages). This prevents the sidebar from jumping to the top when clicking links.
   *
   * If not provided, scroll position will NOT be saved/restored (opt-out of scroll persistence).
   *
   * @example scrollKey="admin-sidebar"
   */
  scrollKey?: string;
}

// Global map to store scroll positions across renders
const scrollPositions = new Map<string, number>();

export default function OverflowDiv({
  disableMask,
  backgroundColor = "var(--background-tint-02)",
  height: minHeight = "2rem",
  scrollKey,

  className,
  ...rest
}: VerticalShadowScrollerProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const pathname = usePathname();

  // Save scroll position on every scroll event (only if scrollKey is provided)
  useEffect(() => {
    if (!scrollKey) return; // Opt-out: no scroll persistence if scrollKey not provided

    const scrollElement = scrollRef.current;
    if (!scrollElement) return;

    const key = scrollKey; // Capture for closure
    const handleScroll = () => {
      scrollPositions.set(key, scrollElement.scrollTop);
    };

    scrollElement.addEventListener("scroll", handleScroll, { passive: true });
    return () => scrollElement.removeEventListener("scroll", handleScroll);
  }, [scrollKey]);

  // Restore scroll position immediately after pathname changes (before paint)
  useLayoutEffect(() => {
    if (!scrollKey) return; // Opt-out: no scroll restoration if scrollKey not provided

    const scrollElement = scrollRef.current;
    if (!scrollElement) return;

    const key = scrollKey; // Capture for type safety
    const savedPosition = scrollPositions.get(key) || 0;
    scrollElement.scrollTop = savedPosition;
  }, [pathname, scrollKey]);

  return (
    <div className="relative flex-1 min-h-0 overflow-y-hidden flex flex-col">
      <div
        ref={scrollRef}
        className="flex-1 min-h-0 overflow-y-auto flex flex-col"
      >
        <div className={cn("flex-1 flex flex-col", className)} {...rest} />
        <div style={{ minHeight }} />
      </div>
      {!disableMask && (
        <div
          className="absolute bottom-0 left-0 right-0 h-[1rem] z-[20] pointer-events-none"
          style={{
            background: `linear-gradient(to bottom, transparent, ${backgroundColor})`,
          }}
        />
      )}
    </div>
  );
}
