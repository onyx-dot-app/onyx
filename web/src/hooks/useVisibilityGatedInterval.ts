"use client";

import { useEffect, useRef } from "react";

/**
 * setInterval that goes quiet while the tab is hidden: ticks are skipped when
 * `document.hidden`, and returning to visibility runs one catch-up tick if a
 * full interval has elapsed. Keeps abandoned background tabs from polling the
 * API forever. Pass `null` to disable.
 */
export function useVisibilityGatedInterval(
  callback: () => void,
  intervalMs: number | null
) {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    if (!intervalMs) return;

    let lastRun = Date.now();
    const run = () => {
      lastRun = Date.now();
      callbackRef.current();
    };

    const intervalId = setInterval(() => {
      if (document.hidden) return;
      run();
    }, intervalMs);

    const handleVisibilityChange = () => {
      if (
        document.visibilityState === "visible" &&
        Date.now() - lastRun >= intervalMs
      ) {
        run();
      }
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      clearInterval(intervalId);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [intervalMs]);
}
