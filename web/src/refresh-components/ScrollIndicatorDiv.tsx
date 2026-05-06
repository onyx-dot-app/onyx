"use client";

import React, { useEffect, useRef, useState, useCallback } from "react";
import { cn } from "@opal/utils";

// Throttle interval for scroll events (~60fps)
const SCROLL_THROTTLE_MS = 16;

/**
 * A scrollable container that shows gradient or shadow indicators when
 * content overflows above or below the visible area.
 *
 * HEIGHT CONSTRAINT REQUIREMENT
 *
 * This component relies on its inner scroll container having a smaller
 * clientHeight than its scrollHeight. For that to happen, the entire
 * ancestor chain must constrain height via flex sizing (flex-1 min-h-0),
 * NOT via percentage heights (h-full).
 *
 * height: 100% resolves to "auto" when the containing block's height is
 * determined by flex layout (flex-auto, flex-1) rather than an explicit
 * height property — this is per the CSS spec. When that happens, the
 * container grows to fit its content and scrollHeight === clientHeight,
 * making scroll indicators invisible.
 *
 * Correct pattern: every ancestor up to the nearest fixed-height boundary
 * must form an unbroken flex column chain using "flex-1 min-h-0":
 *
 *   fixed-height-ancestor  (e.g. h-[500px])
 *     flex flex-col flex-1 min-h-0   <-- use flex-1, NOT h-full
 *       ScrollIndicatorDiv
 *         ...tall content...
 *
 * Common mistakes:
 *  - Using h-full instead of flex-1 min-h-0 anywhere in the chain.
 *  - Placing this inside a parent with overflow-y: auto (e.g. Modal.Body),
 *    which becomes the scroll container instead of this component's inner div.
 */
export interface ScrollIndicatorDivProps
  extends React.HTMLAttributes<HTMLDivElement> {
  // Mask/Shadow options
  disableIndicators?: boolean;
  disableTopIndicator?: boolean;
  disableBottomIndicator?: boolean;
  backgroundColor?: string;
  indicatorHeight?: string;

  // Choose between gradient mask or box shadow
  variant?: "gradient" | "shadow";

  // Optional spacing at bottom (defaults to none)
  bottomSpacing?: string;
}

export default function ScrollIndicatorDiv({
  disableIndicators = false,
  disableTopIndicator = false,
  disableBottomIndicator = false,
  backgroundColor = "var(--background-tint-02)",
  indicatorHeight = "3rem",
  variant = "gradient",
  bottomSpacing,

  className,
  children,
  ...rest
}: ScrollIndicatorDivProps) {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [showTopIndicator, setShowTopIndicator] = useState(false);
  const [showBottomIndicator, setShowBottomIndicator] = useState(false);
  const throttleTimeoutRef = useRef<number | null>(null);
  const isThrottledRef = useRef(false);

  const updateScrollIndicators = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const { scrollTop, scrollHeight, clientHeight } = container;
    const isScrollable = scrollHeight > clientHeight;

    // Show top indicator if scrolled down from top
    setShowTopIndicator(isScrollable && scrollTop > 0);

    // Show bottom indicator if not scrolled to bottom
    // Add small threshold (1px) to account for rounding errors
    setShowBottomIndicator(
      isScrollable && scrollTop < scrollHeight - clientHeight - 1
    );
  }, []);

  // Throttled scroll handler for better performance
  const handleScroll = useCallback(() => {
    if (isThrottledRef.current) return;

    isThrottledRef.current = true;
    updateScrollIndicators();

    throttleTimeoutRef.current = window.setTimeout(() => {
      isThrottledRef.current = false;
      updateScrollIndicators();
    }, SCROLL_THROTTLE_MS);
  }, [updateScrollIndicators]);

  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    // Initial check
    updateScrollIndicators();

    // Update on scroll (throttled)
    container.addEventListener("scroll", handleScroll, { passive: true });

    // Update when the container itself resizes
    const resizeObserver = new ResizeObserver(updateScrollIndicators);
    resizeObserver.observe(container);

    // Update when descendants change (e.g. syntax highlighting mutates the
    // DOM after initial render, which changes scrollHeight without firing
    // resize or scroll events on the container).
    const mutationObserver = new MutationObserver(handleScroll);

    return () => {
      container.removeEventListener("scroll", handleScroll);
      resizeObserver.disconnect();
      mutationObserver.disconnect();
      if (throttleTimeoutRef.current) {
        clearTimeout(throttleTimeoutRef.current);
      }
    };
  }, [updateScrollIndicators, handleScroll]);

  // Update when children change
  useEffect(() => {
    updateScrollIndicators();
  }, [children]);

  const getIndicatorStyle = (direction: "top" | "bottom") => {
    if (variant === "shadow") {
      return {
        height: "2px",
        backgroundColor: backgroundColor,
        boxShadow:
          direction === "top"
            ? "0 -2px 12px 0 var(--shadow-02), 0 0 4px 1px var(--shadow-02)"
            : "0 4px 24px 0 var(--shadow-02), 0 2px 8px 2px var(--shadow-02)",
      };
    }

    // Gradient variant - use full indicator height
    return {
      height: indicatorHeight,
      background:
        direction === "top"
          ? `linear-gradient(to top, transparent, ${backgroundColor})`
          : `linear-gradient(to bottom, transparent, ${backgroundColor})`,
    };
  };

  return (
    <div className="relative flex-1 min-h-0 overflow-y-hidden flex flex-col w-full">
      {/* Top indicator */}
      {!disableIndicators && !disableTopIndicator && showTopIndicator && (
        <div
          className="absolute top-0 left-0 right-0 z-[20] pointer-events-none transition-opacity duration-200"
          style={getIndicatorStyle("top")}
        />
      )}

      {/* Scrollable content */}
      <div
        ref={scrollContainerRef}
        className={cn(
          "flex-1 min-h-0 overflow-y-auto flex flex-col",
          className
        )}
        {...rest}
      >
        {children}
        {bottomSpacing && <div style={{ minHeight: bottomSpacing }} />}
      </div>

      {/* Bottom indicator */}
      {!disableIndicators && !disableBottomIndicator && showBottomIndicator && (
        <div
          className="absolute bottom-0 left-0 right-0 z-[20] pointer-events-none transition-opacity duration-200"
          style={getIndicatorStyle("bottom")}
        />
      )}
    </div>
  );
}
