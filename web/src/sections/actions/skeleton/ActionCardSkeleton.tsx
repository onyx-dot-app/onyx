"use client";

import React from "react";
import { cn } from "@/lib/utils";

interface ActionCardSkeletonProps {
  className?: string;
}

const ActionCardSkeleton: React.FC<ActionCardSkeletonProps> = ({
  className,
}) => {
  return (
    <div
      className={cn(
        "w-full border border-border-01 rounded-16 bg-background-tint-00",
        className
      )}
      role="status"
      aria-label="Loading action card"
    >
      <div className="flex flex-col w-full">
        {/* Header Section */}
        <div className="flex items-start justify-between gap-2 p-3 w-full">
          {/* Left: Icon + Title / Description */}
          <div className="flex gap-2 items-start flex-1 min-w-0 mr-2">
            {/* Icon */}
            <div className="flex items-center px-0 py-0.5 shrink-0">
              <div className="h-7 w-7 rounded-12 bg-background-tint-02 animate-pulse" />
            </div>

            {/* Title & Description */}
            <div className="flex flex-col items-start flex-1 min-w-0 gap-2">
              <div className="h-4 w-1/3 rounded bg-background-tint-02 animate-pulse" />
              <div className="h-3 w-2/3 rounded bg-background-tint-02 animate-pulse" />
            </div>
          </div>

          {/* Right: Actions / View tools button */}
          <div className="flex flex-col gap-2 items-end shrink-0">
            {/* Top row: icon buttons / status */}
            <div className="flex items-center gap-2">
              <div className="h-8 w-8 rounded-full bg-background-tint-02 animate-pulse" />
              <div className="h-8 w-8 rounded-full bg-background-tint-02 animate-pulse" />
            </div>

            {/* View tools button placeholder */}
            <div className="h-8 w-32 rounded-full bg-background-tint-02 animate-pulse" />
          </div>
        </div>
      </div>
    </div>
  );
};

ActionCardSkeleton.displayName = "ActionCardSkeleton";

export default ActionCardSkeleton;
