"use client";

import React from "react";
import { cn } from "@/lib/utils";

export interface VerticalShadowScrollerProps {
  className?: string;
  children?: React.ReactNode;
  disable?: boolean;
}

export default function VerticalShadowScroller({
  className,
  children,
  disable,
}: VerticalShadowScrollerProps) {
  return (
    <div
      className={cn("flex flex-col flex-1 overflow-y-scroll", className)}
      style={{
        WebkitMaskImage: disable
          ? undefined
          : "linear-gradient(to bottom, white calc(100% - 3rem), transparent)",
        maskImage: disable
          ? undefined
          : "linear-gradient(to bottom, white calc(100% - 3rem), transparent)",
      }}
    >
      {children}

      {/* We add some spacing after the masked scroller to make it clear that this is the *end* of the scroller. */}
      <div className="min-h-[0.5rem]" />
    </div>
  );
}
