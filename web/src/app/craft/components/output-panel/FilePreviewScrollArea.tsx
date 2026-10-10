"use client";

import { useLayoutEffect, useRef, type ReactNode } from "react";
import { cn } from "@opal/utils";

import type { FilePreviewScrollPosition } from "@/app/craft/components/output-panel/types";

interface FilePreviewScrollAreaProps extends FilePreviewScrollPosition {
  children: ReactNode;
  padding?: 0 | 4 | 6;
  paddingX?: 0 | 4 | 6;
  fullHeight?: boolean;
}

/** Keeps a viewer's position through hidden tabs and bounded cache eviction. */
export function FilePreviewScrollArea({
  children,
  initialScrollTop = 0,
  onScrollTopChange,
  isActive = true,
  padding = 4,
  paddingX,
  fullHeight = true,
}: FilePreviewScrollAreaProps) {
  const element = useRef<HTMLDivElement>(null);
  const position = useRef(initialScrollTop);
  const restored = useRef(false);
  useLayoutEffect(() => {
    if (isActive && element.current && !restored.current) {
      element.current.scrollTop = position.current;
      restored.current = true;
    }
  }, [isActive]);
  return (
    <div
      ref={element}
      className={cn(
        "overflow-auto",
        fullHeight && "h-full",
        padding === 6 ? "p-6" : padding === 4 ? "p-4" : "p-0",
        paddingX === 6
          ? "px-6"
          : paddingX === 4
            ? "px-4"
            : paddingX === 0 && "px-0"
      )}
      onScroll={(event) => {
        if (!isActive) return;
        position.current = event.currentTarget.scrollTop;
        onScrollTopChange?.(position.current);
      }}
    >
      {children}
    </div>
  );
}
