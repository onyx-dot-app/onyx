"use client";

import "@opal/loaders/styles.css";
import { useLayoutEffect, useRef } from "react";
import { Text, type TextFont } from "@opal/components";
import type { RichStr } from "@opal/types";

/** The wave's width, in pixels. */
const BAND_PX = 40;
/** How fast the wave travels, in pixels per second, on any length of text. */
const RATE_PX_PER_S = 60;
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
 * on wrapped text it runs along each line in reading order. It moves at one
 * rate on any text: the component measures the text's run length (every
 * line fragment) and sets the pass duration from it.
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
      const tail = RATE_PX_PER_S * GAP_S;
      const duration = (length + BAND_PX + tail) / RATE_PX_PER_S;
      wave.style.setProperty("--opal-text-shimmer-band", `${BAND_PX}px`);
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
