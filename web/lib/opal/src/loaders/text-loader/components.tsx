"use client";

import "@opal/loaders/styles.css";
import { Text, type TextFont } from "@opal/components";
import type { RichStr } from "@opal/types";

interface TextLoaderProps {
  /** The text to shimmer, e.g. a status like "Thinking…". */
  children: string | RichStr;

  /** Typography preset. @default "main-ui-action" */
  font?: TextFont;
}

/**
 * Real text with a highlight sweeping across its glyphs, for a status that
 * is still in progress. To stand in for text that has not loaded, use
 * `LineLoader`.
 *
 * The text renders twice: the visible base and an inert clone masked to its
 * own glyphs, which the highlight crosses. Only `translate` animates, so the
 * sweep composites on the GPU.
 */
function TextLoader({ children, font = "main-ui-action" }: TextLoaderProps) {
  return (
    <div className="opal-shimmer-text">
      <Text as="p" font={font} color="inherit">
        {children}
      </Text>
      <div aria-hidden="true" inert className="opal-shimmer-text-overlay">
        <Text as="p" font={font} color="inherit">
          {children}
        </Text>
      </div>
    </div>
  );
}

export { TextLoader, type TextLoaderProps };
