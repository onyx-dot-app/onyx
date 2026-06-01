/* eslint-disable react-hooks/set-state-in-effect -- the 1s interval updates elapsed seconds via setState inside an effect by design. */
// Mirrors web useStreamingDuration, but swaps web's requestAnimationFrame for a
// 1s setInterval: rAF is wasteful when we only update once per second.
import { useState, useEffect, useRef } from "react";

export function useStreamingDuration(
  isStreaming: boolean,
  startTime: number | undefined,
  backendDuration?: number
): number {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastElapsedRef = useRef<number>(0);

  // Backend duration freezes the live timer.
  const shouldRunTimer = isStreaming && backendDuration === undefined;

  useEffect(() => {
    if (!shouldRunTimer || !startTime) {
      // Preserve the last value when merely stopping; only reset on no startTime.
      if (!startTime) {
        setElapsedSeconds(0);
        lastElapsedRef.current = 0;
      }
      return;
    }

    const updateElapsed = () => {
      const now = Date.now();
      const elapsed = Math.floor((now - startTime) / 1000);

      // Only re-render when the whole-second value changes.
      if (elapsed !== lastElapsedRef.current) {
        lastElapsedRef.current = elapsed;
        setElapsedSeconds(elapsed);
      }
    };

    // Run once immediately so the first tick isn't a full second late.
    updateElapsed();
    intervalRef.current = setInterval(updateElapsed, 1000);

    return () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [shouldRunTimer, startTime]);

  return backendDuration !== undefined ? backendDuration : elapsedSeconds;
}
