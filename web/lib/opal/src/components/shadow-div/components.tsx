"use client";

import React, { useState, useEffect, useCallback } from "react";
import { cn } from "@opal/utils";

interface ShadowDivProps extends React.HTMLAttributes<HTMLDivElement> {
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

  /**
   * Fade the content itself via mask-image instead of painting gradient
   * overlays. Use over non-flat backgrounds the gradients can't match.
   */
  mask?: boolean;
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
 * <ShadowDiv className="max-h-80">
 *   <div>Long content...</div>
 *   <div>More content...</div>
 * </ShadowDiv>
 * ```
 *
 * @example
 * // Only show bottom shadow
 * <ShadowDiv bottomOnly className="max-h-80">
 *   <div>Content...</div>
 * </ShadowDiv>
 */
function ShadowDiv({
  backgroundColor = "var(--background-neutral-00)",
  shadowHeight = "1.5rem",
  scrollContainerRef,
  bottomOnly = false,
  topOnly = false,
  mask = false,
  className,
  children,
  style,
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

  const topFade = !bottomOnly && showTopShadow ? shadowHeight : "0px";
  const bottomFade = !topOnly && showBottomShadow ? shadowHeight : "0px";
  const maskImage = `linear-gradient(to bottom, transparent 0, black ${topFade}, black calc(100% - ${bottomFade}), transparent 100%)`;

  return (
    <div className="relative min-h-0 flex flex-col">
      <div
        ref={containerRef}
        className={cn("overflow-y-auto", className)}
        style={
          mask ? { ...style, maskImage, WebkitMaskImage: maskImage } : style
        }
        {...props}
      >
        {children}
      </div>

      {/* Top scroll shadow indicator */}
      {!mask && !bottomOnly && (
        <div
          className={cn(
            "absolute top-0 left-0 right-0 pointer-events-none transition-opacity duration-150",
            showTopShadow ? "opacity-100" : "opacity-0"
          )}
          style={{
            height: shadowHeight,
            background: `linear-gradient(to bottom, ${backgroundColor}, transparent)`,
          }}
        />
      )}

      {/* Bottom scroll shadow indicator */}
      {!mask && !topOnly && (
        <div
          className={cn(
            "absolute bottom-0 left-0 right-0 pointer-events-none transition-opacity duration-150",
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

export { ShadowDiv, type ShadowDivProps };
