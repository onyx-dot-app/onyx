"use client";

import "@opal/loaders/styles.css";
import { spacingToRem, type LineHeight } from "@opal/shared";
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

  /**
   * The line height each bar stands in for. A bar keeps its own height and
   * sits centred in the line, so the loader is as tall as the text or the
   * control it replaces. @default 5 (20px, the main UI line)
   */
  height?: LineHeight;
}

/**
 * Shimmering rectangles standing in for lines of text that have not loaded.
 * To shimmer real text, use `TextLoader`.
 */
function LineLoader({
  lines = 1,
  width = "full",
  height = 5,
}: LineLoaderProps) {
  const strings = useOpalStrings();
  return (
    <div
      role="status"
      aria-label={strings.loading}
      className="flex w-full flex-col"
    >
      {Array.from({ length: lines }, (_, index) => (
        <div
          key={index}
          className="flex w-full items-center"
          style={{ height: spacingToRem(height) }}
        >
          <div
            className={cn(
              "opal-shimmer-block h-3 rounded-04",
              index === lines - 1 ? WIDTH_CLASS[width] : "w-full"
            )}
          />
        </div>
      ))}
    </div>
  );
}

export { LineLoader, type LineLoaderProps, type LineLoaderWidth };
