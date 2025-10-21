"use client";

import React from "react";
import { cn } from "@/lib/utils";

export interface VerticalShadowScrollerProps {
  className?: string;
  children?: React.ReactNode;
  disable?: boolean;
  backgroundColor?: string;
}

export default function VerticalShadowScroller({
  className,
  children,
  disable,
  backgroundColor = "background-tint-02",
}: VerticalShadowScrollerProps) {
  return (
    <div className="flex flex-col flex-1 overflow-y-hidden relative">
      <div className={cn("flex flex-col flex-1 overflow-y-scroll", className)}>
        {children}
        {/* We add some spacing after the masked scroller to make it clear that this is the *end* of the scroller. */}
        <div className="min-h-[0.5rem]" />
      </div>

      {/* Mask Layer */}
      <div
        className="absolute bottom-0 left-0 right-0 h-[3rem]"
        style={{
          background: disable
            ? undefined
            : `linear-gradient(to bottom, transparent, var(--${backgroundColor}))`,
        }}
      />
    </div>
  );
}
