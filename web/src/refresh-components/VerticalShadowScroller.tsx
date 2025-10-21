"use client";

import { cn } from "@/lib/utils";
import React, { useEffect, useRef, useState } from "react";

export interface VerticalShadowScrollerProps {
  className?: string;
  children?: React.ReactNode;
}

export default function VerticalShadowScroller({
  className,
  children,
}: VerticalShadowScrollerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [showBottomShadow, setShowBottomShadow] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const checkScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = container;
      const hasOverflow = scrollHeight > clientHeight;
      const isScrolledToBottom = scrollTop + clientHeight >= scrollHeight - 1;

      // Show bottom shadow if there's content below the visible area
      setShowBottomShadow(hasOverflow && !isScrolledToBottom);
    };

    // Check on mount and when content changes
    checkScroll();

    // Listen for scroll events
    container.addEventListener("scroll", checkScroll);

    // Use ResizeObserver to detect content size changes
    const resizeObserver = new ResizeObserver(checkScroll);
    resizeObserver.observe(container);

    return () => {
      container.removeEventListener("scroll", checkScroll);
      resizeObserver.disconnect();
    };
  }, [children]);

  return (
    <div className="relative flex-1 flex flex-col overflow-y-scroll">
      <div
        ref={containerRef}
        className={cn(
          "flex flex-col flex-1 overflow-y-auto overflow-x-hidden",
          className
        )}
        style={{
          WebkitMaskImage: showBottomShadow
            ? "linear-gradient(to bottom, white calc(100% - 2.5rem), transparent)"
            : undefined,
          maskImage: showBottomShadow
            ? "linear-gradient(to bottom, white calc(100% - 2.5rem), transparent)"
            : undefined,
        }}
      >
        {children}
      </div>
    </div>
  );
}
