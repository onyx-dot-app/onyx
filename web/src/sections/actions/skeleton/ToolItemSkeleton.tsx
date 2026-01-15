"use client";

import React from "react";
import { cn } from "@/lib/utils";

interface ToolItemSkeletonProps {
  className?: string;
}

const ToolItemSkeleton: React.FC<ToolItemSkeletonProps> = ({ className }) => {
  return (
    <div
      className={cn(
        "flex items-start justify-between w-full p-2 rounded-08 border border-border-01 bg-background-tint-00",
        className
      )}
    >
      {/* Left Section: Icon and Content */}
      <div className="flex gap-1 items-start flex-1 min-w-0 pr-2">
        {/* Icon Container Skeleton */}
        <div className="flex items-center justify-center shrink-0">
          <div className="h-5 w-5 rounded bg-background-tint-02 animate-pulse" />
        </div>

        {/* Content Container */}
        <div className="flex flex-col items-start flex-1 min-w-0 gap-1">
          {/* Tool Name Skeleton */}
          <div className="flex items-center w-full min-h-[20px] px-0.5">
            <div className="h-4 w-1/3 rounded bg-background-tint-02 animate-pulse" />
          </div>

          {/* Description Skeleton */}
          <div className="px-0.5 w-full space-y-1">
            <div className="h-3 w-full rounded bg-background-tint-02 animate-pulse" />
            <div className="h-3 w-2/3 rounded bg-background-tint-02 animate-pulse" />
          </div>
        </div>
      </div>

      {/* Right Section: Switch Skeleton */}
      <div className="flex gap-2 items-start justify-end shrink-0">
        <div className="flex items-center justify-center gap-1 h-5 px-0.5 py-0.5">
          <div className="h-5 w-9 rounded-full bg-background-tint-02 animate-pulse" />
        </div>
      </div>
    </div>
  );
};

ToolItemSkeleton.displayName = "ToolItemSkeleton";
export default ToolItemSkeleton;
