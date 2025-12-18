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
  // Optional unique key to identify this scroll container
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

  // Use scrollKey if provided, otherwise generate a stable key on first render
  const instanceKey = useRef<string>(scrollKey || "");
  if (!instanceKey.current) {
    instanceKey.current = `overflow-${Math.random()
      .toString(36)
      .substring(2, 11)}`;
  }

  // Save scroll position on every scroll event
  useEffect(() => {
    const scrollElement = scrollRef.current;
    if (!scrollElement) return;

    const handleScroll = () => {
      scrollPositions.set(instanceKey.current, scrollElement.scrollTop);
    };

    scrollElement.addEventListener("scroll", handleScroll, { passive: true });
    return () => scrollElement.removeEventListener("scroll", handleScroll);
  }, []);

  // Restore scroll position immediately after pathname changes (before paint)
  useLayoutEffect(() => {
    const scrollElement = scrollRef.current;
    if (!scrollElement) return;

    const savedPosition = scrollPositions.get(instanceKey.current) || 0;
    scrollElement.scrollTop = savedPosition;
  }, [pathname]);

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
