"use client";

import "@opal/components/presence/styles.css";
import React, { useEffect, useState } from "react";
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
   * Open the height from zero before the entry, and close it after the exit,
   * so the content around it moves aside smoothly. @default false
   */
  grow?: boolean;
  /** Width preset. @default "full" */
  width?: ExtremaSizeVariants;
  /** Height preset. When omitted, no height class is applied. */
  height?: ExtremaSizeVariants;
  /** Ref forwarded to the root `<div>`. */
  ref?: React.Ref<HTMLDivElement>;
};

// The collapse waits for `transitionend`; this is the fallback if it never fires.
const COLLAPSE_FALLBACK_MS = 400;

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
function Presence({
  children,
  show = true,
  from = "below",
  to,
  grow = false,
  width = "full",
  height,
  ref,
  ...props
}: PresenceProps) {
  const [phase, setPhase] = useState<PresencePhase>(
    show ? "entering" : "hidden"
  );
  const [shownFor, setShownFor] = useState(show);

  if (show !== shownFor) {
    setShownFor(show);
    if (prefersReducedMotion()) {
      setPhase(show ? "shown" : "hidden");
    } else if (show) {
      setPhase("entering");
    } else if (phase !== "hidden") {
      setPhase("leaving");
    }
  }

  // The collapse never stalls when `transitionend` does not arrive.
  useEffect(() => {
    if (phase !== "collapsing") return;
    const fallback = window.setTimeout(
      () => setPhase("hidden"),
      COLLAPSE_FALLBACK_MS
    );
    return () => window.clearTimeout(fallback);
  }, [phase]);

  if (phase === "hidden") return null;

  const motionProps = {
    "data-presence-phase": phase,
    "data-presence-from": from,
    "data-presence-to": to ?? from,
    inert: phase === "leaving" || phase === "collapsing" || undefined,
    onAnimationEnd: (event: React.AnimationEvent<HTMLDivElement>) => {
      // Only this layer's own animation, not one inside the content.
      if (event.target !== event.currentTarget) return;
      if (phase === "entering") setPhase("shown");
      else if (phase === "leaving") setPhase(grow ? "collapsing" : "hidden");
    },
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
      onTransitionEnd={(event) => {
        if (
          phase === "collapsing" &&
          event.target === event.currentTarget &&
          event.propertyName === "grid-template-rows"
        ) {
          setPhase("hidden");
        }
      }}
    >
      <div {...motionProps} className="opal-presence-motion">
        {children}
      </div>
    </div>
  );
}

export { Presence, type PresenceProps, type PresenceSide };
