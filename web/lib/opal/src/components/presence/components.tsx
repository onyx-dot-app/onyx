"use client";

import "@opal/components/presence/styles.css";
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { cn } from "@opal/utils";
import type { ExtremaSizeVariants, WithoutStyles } from "@opal/types";
import { heightVariants, widthVariants } from "@opal/shared";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Where the content comes from or goes to. `below`: 8px down. `end` /
 * `start`: 8px toward the inline end / start, mirrored in right-to-left text.
 * `none`: a plain fade.
 */
type PresenceSide = "below" | "end" | "start" | "none";

/** shown ↔ leaving → (collapsing →) hidden → entering → shown */
type PresencePhase = "entering" | "shown" | "leaving" | "collapsing" | "hidden";

type PresenceProps = WithoutStyles<React.HTMLAttributes<HTMLDivElement>> & {
  children: React.ReactNode;
  /**
   * Whether the content is present. `true` plays the entry; a change to
   * `false` plays the exit, then renders nothing. @default true
   */
  show?: boolean;
  /** Where the content enters from. @default "below" */
  from?: PresenceSide;
  /** Where the content leaves to. @default the same side as `from` */
  to?: PresenceSide;
  /**
   * Play the entry when the content is present on mount. `false` shows it at
   * once; later changes of `show` still animate. @default true
   */
  appear?: boolean;
  /**
   * Open the height from zero before the entry, and close it after the exit,
   * so the content around it moves aside smoothly. @default false
   */
  grow?: boolean;
  /** Called once the exit has finished and the content is gone. */
  onExited?: () => void;
  /** Width preset. @default "full" */
  width?: ExtremaSizeVariants;
  /** Height preset. When omitted, no height class is applied. */
  height?: ExtremaSizeVariants;
  /** Ref forwarded to the root `<div>`. */
  ref?: React.Ref<HTMLDivElement>;
};

/**
 * Which way the content moves. `forward`: the old content leaves toward the
 * inline start and the new content arrives from the inline end. `back` is the
 * mirror. Both follow the text direction.
 */
type PresenceSwapDirection = "forward" | "back";

/**
 * Which size follows the content. `block`: the height, for stacked content.
 * `inline`: the width, for content in a row, like a button whose label
 * changes.
 */
type PresenceSwapAxis = "block" | "inline";

/** idle → exiting → resizing → idle */
type PresenceSwapPhase = "idle" | "exiting" | "resizing";

type PresenceSwapProps = WithoutStyles<React.HTMLAttributes<HTMLDivElement>> & {
  /** Identity of the content. A change plays the swap. */
  swapKey: React.Key;
  /** @default "forward" */
  direction?: PresenceSwapDirection;
  /** @default "block" */
  axis?: PresenceSwapAxis;
  children: React.ReactNode;
};

// A transition waits for `transitionend`; this is the fallback if it never
// fires.
const TRANSITION_FALLBACK_MS = 400;

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

// ---------------------------------------------------------------------------
// Presence
// ---------------------------------------------------------------------------

/**
 * Animates content in when it appears and out when it goes. Drive it with
 * `show`: the exit plays before the content is removed. Without `show`, it
 * plays the entry once, on mount. Change the `key` to play the entry again.
 * To replace content with an exit and an entry, use `Presence.Swap`.
 *
 * @example
 * ```tsx
 * <Presence key={pathname} height="full">
 *   {page}
 * </Presence>
 *
 * <Presence show={hasPrevious} from="end" width="fit">
 *   <BackButton />
 * </Presence>
 * ```
 */
function PresenceRoot({
  children,
  show = true,
  from = "below",
  to,
  appear = true,
  grow = false,
  onExited,
  width = "full",
  height,
  ref,
  ...props
}: PresenceProps) {
  const [phase, setPhase] = useState<PresencePhase>(
    show ? (appear ? "entering" : "shown") : "hidden"
  );
  const [shownFor, setShownFor] = useState(show);
  // With `appear={false}`, `grow` content present on mount also skips the
  // height opening, until it first leaves.
  const [skipOpen, setSkipOpen] = useState(!appear && show);
  // An exit skipped for reduced motion reports `onExited` after the commit.
  const [skippedExit, setSkippedExit] = useState(false);

  if (show !== shownFor) {
    setShownFor(show);
    if (!show) setSkipOpen(false);
    if (prefersReducedMotion()) {
      setPhase(show ? "shown" : "hidden");
      if (!show && phase !== "hidden") setSkippedExit(true);
    } else if (show) {
      setPhase("entering");
    } else if (phase !== "hidden") {
      setPhase("leaving");
    }
  }

  // Hide and report in the same update, so a parent can render what comes
  // next without a frame of empty space.
  function finishExit() {
    setPhase("hidden");
    onExited?.();
  }

  useEffect(() => {
    if (!skippedExit) return;
    setSkippedExit(false);
    onExited?.();
  }, [skippedExit, onExited]);

  // The collapse never stalls when `transitionend` does not arrive.
  const finishExitRef = useRef(finishExit);
  useLayoutEffect(() => {
    finishExitRef.current = finishExit;
  });
  useEffect(() => {
    if (phase !== "collapsing") return;
    const fallback = window.setTimeout(
      () => finishExitRef.current(),
      TRANSITION_FALLBACK_MS
    );
    return () => window.clearTimeout(fallback);
  }, [phase]);

  if (phase === "hidden") return null;

  function advance(event: React.AnimationEvent<HTMLDivElement>) {
    // Only this layer's own animation, not one inside the content.
    if (event.target !== event.currentTarget) return;
    if (phase === "entering") setPhase("shown");
    else if (phase === "leaving") {
      if (grow) setPhase("collapsing");
      else finishExit();
    }
  }

  const motionProps = {
    "data-presence-phase": phase,
    "data-presence-from": from,
    "data-presence-to": to ?? from,
    inert: phase === "leaving" || phase === "collapsing" || undefined,
    onAnimationEnd: advance,
    // Reduced motion turned on mid-animation removes it without an end event.
    onAnimationCancel: advance,
  };
  const rootClassName = cn(
    "opal-presence",
    widthVariants[width],
    height && heightVariants[height]
  );

  if (!grow) {
    return (
      <div
        {...props}
        {...motionProps}
        ref={ref}
        className={cn(rootClassName, "opal-presence-motion")}
      >
        {children}
      </div>
    );
  }

  // The root opens and closes the height; the inner element fades.
  return (
    <div
      {...props}
      ref={ref}
      className={rootClassName}
      data-presence-grow=""
      data-presence-phase={phase}
      data-presence-skip-open={skipOpen || undefined}
      onTransitionEnd={(event) => {
        if (
          phase === "collapsing" &&
          event.target === event.currentTarget &&
          event.propertyName === "grid-template-rows"
        ) {
          finishExit();
        }
      }}
    >
      <div {...motionProps} className="opal-presence-motion">
        {children}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Presence.Swap
// ---------------------------------------------------------------------------

/**
 * Replaces one piece of content with another, like a carousel step: the old
 * content leaves through a `Presence` exit, the box resizes to the new
 * content, then the new content plays a `Presence` entry from the other side.
 * Content changes that keep the same `swapKey` resize smoothly too.
 *
 * @example
 * ```tsx
 * <Presence.Swap swapKey={step} direction={isForward ? "forward" : "back"}>
 *   <StepCard step={step} />
 * </Presence.Swap>
 * ```
 */
function PresenceSwap({
  swapKey,
  direction = "forward",
  axis = "block",
  children,
  ...props
}: PresenceSwapProps) {
  const [shownKey, setShownKey] = useState(swapKey);
  const [phase, setPhase] = useState<PresenceSwapPhase>("idle");
  const [motionDirection, setMotionDirection] =
    useState<PresenceSwapDirection>(direction);
  // Each swap mounts a new `Presence`; the first one shows without an entry.
  const [generation, setGeneration] = useState(0);
  const [outgoing, setOutgoing] = useState<React.ReactNode>(null);
  const [size, setSize] = useState<number | null>(null);

  const contentRef = useRef<HTMLDivElement>(null);
  // The last children shown for `shownKey`: what leaves when the key changes.
  const shownChildrenRef = useRef<React.ReactNode>(children);

  if (swapKey !== shownKey) {
    setShownKey(swapKey);
    setMotionDirection(direction);
    if (prefersReducedMotion()) {
      setPhase("idle");
    } else if (phase === "idle") {
      setOutgoing(shownChildrenRef.current);
      setPhase("exiting");
    }
    // Mid-exit or mid-resize, the swap goes on and lands on the newest key.
  }

  // Keep the leaving snapshot current while the shown content is on screen.
  useLayoutEffect(() => {
    if (phase === "idle") shownChildrenRef.current = children;
  });

  // Track the content's size on `axis`, so the box animates to every new size.
  useLayoutEffect(() => {
    const content = contentRef.current;
    if (!content) return;
    const measure = () =>
      setSize(axis === "inline" ? content.offsetWidth : content.offsetHeight);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(content);
    return () => observer.disconnect();
  }, [axis]);

  // Resizing: go straight on when the new content is the same size as the old,
  // and never stall if `transitionend` does not arrive. Runs once per phase
  // change, against the size the box had when the resize began.
  const sizeRef = useRef(size);
  useLayoutEffect(() => {
    sizeRef.current = size;
  }, [size]);
  useLayoutEffect(() => {
    if (phase !== "resizing") return;
    const content = contentRef.current;
    const contentSize =
      axis === "inline" ? content?.offsetWidth : content?.offsetHeight;
    if (!content || contentSize === sizeRef.current) {
      setPhase("idle");
      return;
    }
    const fallback = window.setTimeout(
      () => setPhase("idle"),
      TRANSITION_FALLBACK_MS
    );
    return () => window.clearTimeout(fallback);
  }, [phase, axis]);

  const sizeProperty = axis === "inline" ? "width" : "height";
  const forward = motionDirection === "forward";

  return (
    <div
      {...props}
      className="opal-presence-swap"
      data-swap-axis={axis}
      style={
        size === null
          ? undefined
          : axis === "inline"
            ? { width: size }
            : { height: size }
      }
      onTransitionEnd={(event) => {
        if (
          phase === "resizing" &&
          event.target === event.currentTarget &&
          event.propertyName === sizeProperty
        ) {
          setPhase("idle");
        }
      }}
    >
      <div
        ref={contentRef}
        className="opal-presence-swap-content"
        data-swap-phase={phase}
      >
        <PresenceRoot
          key={generation}
          show={phase !== "exiting"}
          appear={generation > 0}
          from={forward ? "end" : "start"}
          to={forward ? "start" : "end"}
          width={axis === "inline" ? "fit" : "full"}
          onExited={() => {
            setGeneration((current) => current + 1);
            setPhase("resizing");
          }}
        >
          {phase === "exiting" ? outgoing : children}
        </PresenceRoot>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

const Presence = Object.assign(PresenceRoot, { Swap: PresenceSwap });

export {
  Presence,
  type PresenceProps,
  type PresenceSide,
  type PresenceSwapProps,
  type PresenceSwapDirection,
  type PresenceSwapAxis,
};
