"use client";

import React, { useState, useEffect, useCallback } from "react";
import { cn } from "@/lib/utils";

export interface ShadowDivProps extends React.HTMLAttributes<HTMLDivElement> {
  /**
   * Background color to use for the shadow gradients.
   * Defaults to --background-neutral-00
   */
  backgroundColor?: string;

  /**
   * Height of the shadow gradients.
   * Defaults to 1.5rem (24px)
   */
  shadowHeight?: string;

  /**
   * Ref for the scrollable container (useful for programmatic scrolling)
   */
  scrollContainerRef?: React.RefObject<HTMLDivElement | null>;

  /**
   * Show only bottom shadow (similar to OverflowDiv behavior)
   */
  bottomOnly?: boolean;

  /**
   * Show only top shadow
   */
  topOnly?: boolean;
}

/**
 * ShadowDiv - A scrollable container with automatic top/bottom shadow indicators
 *
 * This component wraps content in a scrollable div and automatically displays
 * gradient shadows at the top and/or bottom to indicate there's more content
 * to scroll in those directions.
 *
 * @example
 * ```tsx
 * <ShadowDiv className="max-h-[20rem]">
 *   <div>Long content...</div>
 *   <div>More content...</div>
 * </ShadowDiv>
 * ```
 *
 * @example
 * // Only show bottom shadow
 * <ShadowDiv bottomOnly className="max-h-[20rem]">
 *   <div>Content...</div>
 * </ShadowDiv>
 */
export default function ShadowDiv({
  backgroundColor = "var(--background-neutral-00)",
  shadowHeight = "1.5rem",
  scrollContainerRef,
  bottomOnly = false,
  topOnly = false,
  className,
  children,
  ...props
}: ShadowDivProps) {
  const [showTopShadow, setShowTopShadow] = useState(false);
  const [showBottomShadow, setShowBottomShadow] = useState(false);
  const internalRef = React.useRef<HTMLDivElement>(null);
  const containerRef = scrollContainerRef || internalRef;

  const checkScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    // Show top shadow if scrolled down
    if (!bottomOnly) {
      setShowTopShadow(container.scrollTop > 1);
    }

    // Show bottom shadow if there's more content to scroll down
    if (!topOnly) {
      const hasMoreBelow =
        container.scrollHeight - container.scrollTop - container.clientHeight >
        1;
      setShowBottomShadow(hasMoreBelow);
    }
  }, [containerRef, bottomOnly, topOnly]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // Check initial state
    checkScroll();

    container.addEventListener("scroll", checkScroll);
    // Also check on resize in case content changes
    const resizeObserver = new ResizeObserver(checkScroll);
    resizeObserver.observe(container);

    return () => {
      container.removeEventListener("scroll", checkScroll);
      resizeObserver.disconnect();
    };
  }, [containerRef, checkScroll]);

  return (
    <div className="relative">
      <div
        ref={containerRef}
        className={cn("overflow-y-auto", className)}
        {...props}
      >
        {children}
      </div>

      {/* Top scroll shadow indicator */}
      {!bottomOnly && (
        <div
          className={cn(
            "absolute top-0 left-0 right-0 pointer-events-none",
            showTopShadow ? "opacity-100" : "opacity-0"
          )}
          style={{
            height: shadowHeight,
            background: `linear-gradient(to bottom, ${backgroundColor}, transparent)`,
          }}
        />
      )}

      {/* Bottom scroll shadow indicator */}
      {!topOnly && (
        <div
          className={cn(
            "absolute bottom-0 left-0 right-0 pointer-events-none",
            showBottomShadow ? "opacity-100" : "opacity-0"
          )}
          style={{
            height: shadowHeight,
            background: `linear-gradient(to top, ${backgroundColor}, transparent)`,
          }}
        />
      )}
    </div>
  );
}
