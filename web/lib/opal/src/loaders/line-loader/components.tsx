"use client";

import "@opal/loaders/styles.css";
import { useOpalStrings } from "@opal/strings";
import { cn } from "@opal/utils";

type LineLoaderWidth = "full" | "3/4" | "2/3" | "1/2" | "1/3" | "1/4";

const WIDTH_CLASS: Record<LineLoaderWidth, string> = {
  full: "w-full",
  "3/4": "w-3/4",
  "2/3": "w-2/3",
  "1/2": "w-1/2",
  "1/3": "w-1/3",
  "1/4": "w-1/4",
};

interface LineLoaderProps {
  /** How many lines of text to stand in for. @default 1 */
  lines?: number;

  /** Width of the last line; earlier lines span the full width. @default "full" */
  width?: LineLoaderWidth;
}

/**
 * Shimmering rectangles standing in for lines of text that have not loaded.
 * To shimmer real text, use `TextLoader`.
 */
function LineLoader({ lines = 1, width = "full" }: LineLoaderProps) {
  const strings = useOpalStrings();
  return (
    <div
      role="status"
      aria-label={strings.loading}
      className="flex w-full flex-col gap-2"
    >
      {Array.from({ length: lines }, (_, index) => (
        <div
          key={index}
          className={cn(
            "opal-shimmer-block h-3 rounded-04",
            index === lines - 1 ? WIDTH_CLASS[width] : "w-full"
          )}
        />
      ))}
    </div>
  );
}

export { LineLoader, type LineLoaderProps, type LineLoaderWidth };
