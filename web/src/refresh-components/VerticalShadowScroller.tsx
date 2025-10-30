"use client";

import React from "react";
import { cn } from "@/lib/utils";

export interface VerticalShadowScrollerProps {
  className?: string;
  children?: React.ReactNode;
  disable?: boolean;
  backgroundColor?: string;
  height?: string;
}

export default function VerticalShadowScroller({
  className,
  children,
  disable,
  backgroundColor = "var(--background-tint-02)",
  height: minHeight = "2rem",
}: VerticalShadowScrollerProps) {
  return (
    <div className="relative flex-1 min-h-0 overflow-y-hidden flex flex-col">
      <div className="flex-1 min-h-0 overflow-y-auto flex flex-col">
        <div className={cn("flex-1 flex flex-col", className)}>{children}</div>
        <div style={{ minHeight }} />
      </div>
      <div
        className="absolute bottom-0 left-0 right-0 h-[3rem] z-[20] pointer-events-none"
        style={{
          background: disable
            ? undefined
            : `linear-gradient(to bottom, transparent, ${backgroundColor})`,
        }}
      />
    </div>
  );
}
