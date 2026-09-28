"use client";

import React, { useState, useEffect, useCallback } from "react";
import { cn } from "@opal/utils";
import { spacingToRem } from "@opal/shared";
import type { Spacing } from "@opal/types";

type ShadowDirection = "top-and-bottom" | "top-only" | "bottom-only";

/**
 * How the edges fade. `"shadow"` paints translucent gradients over the
 * content; `"mask"` fades the content itself via mask-image, for surfaces
 * a painted gradient could not match.
 */
type ShadowDivVariant = "shadow" | "mask";

interface ShadowDivProps extends React.HTMLAttributes<HTMLDivElement> {
  /**
   * Height of each gradient, as a spacing step (`N / 4` rem).
   * Defaults to 6 (1.5rem).
   */
  shadowHeight?: Spacing;

  /**
   * Ref for the scrollable container (useful for programmatic scrolling)
   */
  scrollContainerRef?: React.RefObject<HTMLDivElement | null>;

  /**
   * Which edges get a shadow.
   * Defaults to both.
   */
  shadowDirection?: ShadowDirection;

  /**
   * How the edges fade.
   * Defaults to `"shadow"`.
   */
  variant?: ShadowDivVariant;

  /**
   * Class for the outer wrapper (e.g. flex sizing within a parent column).
   */
  containerClassName?: string;
}

// A translucent black in both themes, so the gradients read as a shadow on
// any surface instead of matching one or lifting in dark mode.
const SHADOW_COLOR = "var(--shadow-dark-01)";

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
 * <ShadowDiv shadowDirection="bottom-only" className="max-h-80">
 *   <div>Content...</div>
 * </ShadowDiv>
 */
function ShadowDiv({
  shadowHeight = 6,
  scrollContainerRef,
  shadowDirection = "top-and-bottom",
  variant = "shadow",
  containerClassName,
  className,
  children,
  style,
  ...props
}: ShadowDivProps) {
  const [showTopShadow, setShowTopShadow] = useState(false);
  const [showBottomShadow, setShowBottomShadow] = useState(false);
  const internalRef = React.useRef<HTMLDivElement>(null);
  const containerRef = scrollContainerRef || internalRef;

  const showTop = shadowDirection !== "bottom-only";
  const showBottom = shadowDirection !== "top-only";

  const checkScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    // Show top shadow if scrolled down
    if (showTop) {
      setShowTopShadow(container.scrollTop > 1);
    }

    // Show bottom shadow if there's more content to scroll down
    if (showBottom) {
      const hasMoreBelow =
        container.scrollHeight - container.scrollTop - container.clientHeight >
        1;
      setShowBottomShadow(hasMoreBelow);
    }
  }, [containerRef, showTop, showBottom]);

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

  const fadeHeight = spacingToRem(shadowHeight);
  const topFade = showTop && showTopShadow ? fadeHeight : "0px";
  const bottomFade = showBottom && showBottomShadow ? fadeHeight : "0px";
  const maskImage = `linear-gradient(to bottom, transparent 0, black ${topFade}, black calc(100% - ${bottomFade}), transparent 100%)`;

  return (
    <div className={cn("relative min-h-0 flex flex-col", containerClassName)}>
      <div
        ref={containerRef}
        className={cn("overflow-y-auto", className)}
        style={
          variant === "mask"
            ? { ...style, maskImage, WebkitMaskImage: maskImage }
            : style
        }
        {...props}
      >
        {children}
      </div>

      {/* Top scroll shadow indicator */}
      {variant === "shadow" && showTop && (
        <div
          className={cn(
            "absolute top-0 start-0 end-0 pointer-events-none transition-opacity duration-150",
            showTopShadow ? "opacity-100" : "opacity-0"
          )}
          style={{
            height: fadeHeight,
            background: `linear-gradient(to bottom, ${SHADOW_COLOR}, transparent)`,
          }}
        />
      )}

      {/* Bottom scroll shadow indicator */}
      {variant === "shadow" && showBottom && (
        <div
          className={cn(
            "absolute bottom-0 start-0 end-0 pointer-events-none transition-opacity duration-150",
            showBottomShadow ? "opacity-100" : "opacity-0"
          )}
          style={{
            height: fadeHeight,
            background: `linear-gradient(to top, ${SHADOW_COLOR}, transparent)`,
          }}
        />
      )}
    </div>
  );
}

export {
  ShadowDiv,
  type ShadowDivProps,
  type ShadowDirection,
  type ShadowDivVariant,
};
