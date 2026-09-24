"use client";

import { useCallback, useEffect, useState } from "react";

type PresenceState = "open" | "closed";

/**
 * Keeps an element mounted one exit animation longer than its `open` flag,
 * so it can animate out without living in the tree while closed.
 *
 * Render while `mounted`, put `state` on the element as `data-state` for
 * the CSS keyframes, and attach `onAnimationEnd` so the exit unmounts as
 * soon as its animation finishes. `exitFallbackMs` unmounts anyway when no
 * animation runs (reduced motion, a test DOM), so nothing can stick.
 */
export default function usePresence(open: boolean, exitFallbackMs = 160) {
  const [mounted, setMounted] = useState(open);

  useEffect(() => {
    if (open) {
      setMounted(true);
      return;
    }
    const id = window.setTimeout(() => setMounted(false), exitFallbackMs);
    return () => window.clearTimeout(id);
  }, [open, exitFallbackMs]);

  const onAnimationEnd = useCallback(
    (event: React.AnimationEvent<HTMLElement>) => {
      // Only the element's own exit, not a child's animation bubbling up.
      if (!open && event.target === event.currentTarget) setMounted(false);
    },
    [open]
  );

  const state: PresenceState = open ? "open" : "closed";
  return { mounted, state, onAnimationEnd };
}
