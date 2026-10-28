"use client";

import "@opal/components/swap/styles.css";
import React, { useLayoutEffect, useRef, useState } from "react";
import type { WithoutStyles } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Which way the content moves. `forward`: the old content leaves toward the
 * inline start and the new content arrives from the inline end. `back` is the
 * mirror. Both follow the text direction.
 */
type SwapDirection = "forward" | "back";

/** idle → exiting → resizing → entering → idle */
type SwapPhase = "idle" | "exiting" | "resizing" | "entering";

type SwapProps = WithoutStyles<React.HTMLAttributes<HTMLDivElement>> & {
  /** Identity of the content. A change plays the swap. */
  swapKey: React.Key;
  /** @default "forward" */
  direction?: SwapDirection;
  children: React.ReactNode;
};

// The resize waits for `transitionend`; this is the fallback if it never fires.
const RESIZE_FALLBACK_MS = 400;

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

// ---------------------------------------------------------------------------
// Swap
// ---------------------------------------------------------------------------

/**
 * Swaps one piece of content for another, like a carousel step: the old
 * content fades out sideways, the height adjusts to the new content, then the
 * new content fades in from the other side. Content changes that keep the same
 * `swapKey` resize smoothly too.
 *
 * @example
 * ```tsx
 * <Swap swapKey={step} direction={isForward ? "forward" : "back"}>
 *   <StepCard step={step} />
 * </Swap>
 * ```
 */
function Swap({
  swapKey,
  direction = "forward",
  children,
  ...props
}: SwapProps) {
  const [shownKey, setShownKey] = useState(swapKey);
  const [phase, setPhase] = useState<SwapPhase>("idle");
  const [motionDirection, setMotionDirection] =
    useState<SwapDirection>(direction);
  const [outgoing, setOutgoing] = useState<React.ReactNode>(null);
  const [height, setHeight] = useState<number | null>(null);

  const contentRef = useRef<HTMLDivElement>(null);
  // The last children shown for `shownKey`: what leaves when the key changes.
  const shownChildrenRef = useRef<React.ReactNode>(children);

  if (swapKey !== shownKey) {
    setShownKey(swapKey);
    setMotionDirection(direction);
    if (prefersReducedMotion()) {
      setPhase("idle");
    } else if (phase === "idle" || phase === "entering") {
      setOutgoing(shownChildrenRef.current);
      setPhase("exiting");
    }
    // Mid-exit or mid-resize, the swap goes on and lands on the newest key.
  }

  // Keep the leaving snapshot current while the shown content is on screen.
  useLayoutEffect(() => {
    if (phase === "idle" || phase === "entering") {
      shownChildrenRef.current = children;
    }
  });

  // Track the content's height, so the box animates to every new size.
  useLayoutEffect(() => {
    const content = contentRef.current;
    if (!content) return;
    setHeight(content.offsetHeight);
    const observer = new ResizeObserver(() => {
      setHeight(content.offsetHeight);
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, []);

  // Resizing: go straight on when the new content is as tall as the old, and
  // never stall if `transitionend` does not arrive. Runs once per phase change,
  // against the height the box had when the resize began.
  const heightRef = useRef(height);
  useLayoutEffect(() => {
    heightRef.current = height;
  }, [height]);
  useLayoutEffect(() => {
    if (phase !== "resizing") return;
    const content = contentRef.current;
    if (!content || content.offsetHeight === heightRef.current) {
      setPhase("entering");
      return;
    }
    const fallback = window.setTimeout(
      () => setPhase("entering"),
      RESIZE_FALLBACK_MS
    );
    return () => window.clearTimeout(fallback);
  }, [phase]);

  return (
    <div
      {...props}
      className="opal-swap"
      style={height === null ? undefined : { height }}
      onTransitionEnd={(event) => {
        if (
          phase === "resizing" &&
          event.target === event.currentTarget &&
          event.propertyName === "height"
        ) {
          setPhase("entering");
        }
      }}
    >
      <div
        ref={contentRef}
        className="opal-swap-content"
        data-swap-phase={phase}
        data-swap-direction={motionDirection}
        inert={phase === "exiting" || undefined}
        aria-hidden={phase === "exiting" || undefined}
        onAnimationEnd={(event) => {
          // Only this layer's own animation, not one inside the content.
          if (event.target !== event.currentTarget) return;
          if (phase === "exiting") setPhase("resizing");
          else if (phase === "entering") setPhase("idle");
        }}
      >
        {phase === "exiting" ? outgoing : children}
      </div>
    </div>
  );
}

export { Swap, type SwapProps, type SwapDirection };
