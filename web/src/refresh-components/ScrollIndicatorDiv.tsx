"use client";

import React, { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

export interface ScrollIndicatorDivProps
  extends React.HTMLAttributes<HTMLDivElement> {
  // Mask/Shadow options
  disableIndicators?: boolean;
  backgroundColor?: string;
  indicatorHeight?: string;

  // Choose between gradient mask or box shadow
  variant?: "gradient" | "shadow";

  // Optional spacing at bottom (defaults to none)
  bottomSpacing?: string;
}

export default function ScrollIndicatorDiv({
  disableIndicators = false,
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

  const updateScrollIndicators = () => {
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
  };

  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    // Initial check
    updateScrollIndicators();

    // Update on scroll
    container.addEventListener("scroll", updateScrollIndicators);

    // Update on resize (in case content changes)
    const resizeObserver = new ResizeObserver(updateScrollIndicators);
    resizeObserver.observe(container);

    return () => {
      container.removeEventListener("scroll", updateScrollIndicators);
      resizeObserver.disconnect();
    };
  }, []);

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
      {!disableIndicators && showTopIndicator && (
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
      {!disableIndicators && showBottomIndicator && (
        <div
          className="absolute bottom-0 left-0 right-0 z-[20] pointer-events-none transition-opacity duration-200"
          style={getIndicatorStyle("bottom")}
        />
      )}
    </div>
  );
}
