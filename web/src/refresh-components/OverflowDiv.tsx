"use client";

import React from "react";
import { cn } from "@/lib/utils";

export interface VerticalShadowScrollerProps
  extends React.HtmlHTMLAttributes<HTMLDivElement> {
  // Mask related
  disableMask?: boolean;
  backgroundColor?: string;
  height?: string;
}

export default function OverflowDiv({
  disableMask,
  backgroundColor = "var(--background-tint-02)",
  height: minHeight = "2rem",

  className,
  ...rest
}: VerticalShadowScrollerProps) {
  return (
    <div className="relative flex-1 min-h-0 overflow-y-hidden flex flex-col">
      <div className="flex-1 min-h-0 overflow-y-auto flex flex-col">
        <div className={cn("flex-1 flex flex-col", className)} {...rest} />
        <div style={{ minHeight }} />
      </div>
      <div
        className="absolute bottom-0 left-0 right-0 h-[3rem] z-[20] pointer-events-none"
        style={{
          background: disableMask
            ? undefined
            : `linear-gradient(to bottom, transparent, ${backgroundColor})`,
        }}
      />
    </div>
  );
}
