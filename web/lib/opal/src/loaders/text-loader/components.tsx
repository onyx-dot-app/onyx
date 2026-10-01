"use client";

import "@opal/loaders/styles.css";
import { useLayoutEffect, useRef } from "react";
import { Text, type TextFont } from "@opal/components";
import type { RichStr } from "@opal/types";

/** The wave's narrowest, in pixels. */
const MIN_BAND_PX = 40;
/** On longer text the wave grows to this share of the text's length. */
const BAND_SHARE = 0.4;
/** How long the wave takes to cross the text, in seconds. Its rate scales
 * with the text's length, so every crossing takes this long. */
const CROSSING_S = 2;
/** The pause between waves, in seconds. */
const GAP_S = 1;

interface TextLoaderProps {
  /** The text to shimmer, e.g. a status like "Thinking…". */
  children: string | RichStr;

  /** Typography preset. @default "main-ui-action" */
  font?: TextFont;
}

/**
 * Real text with a wave sweeping across its glyphs, for a status that is
 * still in progress. To stand in for text that has not loaded, use
 * `LineLoader`.
 *
 * The wave is the background of the inline text, clipped to its glyphs, so
 * on wrapped text it runs along each line in reading order. The component
 * measures the text's run length (every line fragment) and scales the wave's
 * width and rate to it.
 */
function TextLoader({ children, font = "main-ui-action" }: TextLoaderProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const waveRef = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    const root = rootRef.current;
    const wave = waveRef.current;
    if (!root || !wave) return;

    function measure() {
      if (!wave) return;
      // An inline element's run length is the sum of its line fragments.
      const length = Array.from(wave.getClientRects()).reduce(
        (total, rect) => total + rect.width,
        0
      );
      const band = Math.max(MIN_BAND_PX, length * BAND_SHARE);
      const rate = (length + band) / CROSSING_S;
      // The pause is distance travelled off the end at this text's rate.
      const tail = rate * GAP_S;
      const duration = CROSSING_S + GAP_S;
      wave.style.setProperty("--opal-text-shimmer-band", `${band}px`);
      wave.style.setProperty("--opal-text-shimmer-tail", `${tail}px`);
      wave.style.setProperty("--opal-text-shimmer-duration", `${duration}s`);
    }

    measure();
    // A new width can rewrap the text and change its run length.
    const observer = new ResizeObserver(measure);
    observer.observe(root);
    return () => observer.disconnect();
  }, [children, font]);

  return (
    <div ref={rootRef} className="opal-text-loader">
      <span ref={waveRef} className="opal-text-loader-wave">
        <Text font={font} color="inherit">
          {children}
        </Text>
      </span>
    </div>
  );
}

export { TextLoader, type TextLoaderProps };
