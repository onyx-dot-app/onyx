"use client";

import React from "react";
import { cn } from "@/lib/utils";

export interface VerticalShadowScrollerProps
  extends React.HtmlHTMLAttributes<HTMLDivElement> {
  disableMask?: boolean;
  height?: string;
}

export default function OverflowDiv({
  disableMask,
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
      {!disableMask && (
        <div className="absolute bottom-0 left-0 right-0 border-t border-border z-[20] pointer-events-none" />
      )}
    </div>
  );
}
