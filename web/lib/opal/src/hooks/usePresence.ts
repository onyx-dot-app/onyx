"use client";

import { useCallback, useEffect, useState } from "react";

type PresenceState = "open" | "closed";

/**
 * Keeps an element mounted one exit animation longer than its `open` flag,
 * so it can animate out without living in the tree while closed. Opening
 * mounts in the same render as `open`, so effects that need the DOM on open
 * find it; only the exit is deferred.
 *
 * Render while `mounted`, put `state` on the element as `data-state` for
 * the CSS keyframes, and attach `onAnimationEnd` so the exit unmounts as
 * soon as its animation finishes. `exitFallbackMs` unmounts anyway when no
 * animation runs (reduced motion, a test DOM), so nothing can stick.
 */
export default function usePresence(open: boolean, exitFallbackMs = 160) {
  // True from the moment `open` drops until the exit animation ends.
  const [exiting, setExiting] = useState(false);

  useEffect(() => {
    if (open) {
      // Re-opening mid-exit cancels the exit in place.
      setExiting(false);
      return;
    }
    setExiting(true);
    const id = window.setTimeout(() => setExiting(false), exitFallbackMs);
    return () => window.clearTimeout(id);
  }, [open, exitFallbackMs]);

  const onAnimationEnd = useCallback(
    (event: React.AnimationEvent<HTMLElement>) => {
      // Only the element's own exit, not a child's animation bubbling up.
      if (!open && event.target === event.currentTarget) setExiting(false);
    },
    [open]
  );

  const state: PresenceState = open ? "open" : "closed";
  return { mounted: open || exiting, state, onAnimationEnd };
}
