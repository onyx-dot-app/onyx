// Live elapsed-seconds timer for the streaming header. Port of web's useStreamingDuration, with the
// RAF loop swapped for a setInterval poll — deterministic under jest fake timers, and RN gains
// nothing from RAF here.

import { useEffect, useRef, useState } from "react";

// Poll faster than 1s so the whole-second boundary stays crisp (web's RAF was ~16ms).
const DURATION_TICK_MS = 250;

export function useStreamingDuration(
  isStreaming: boolean,
  startTime: number | undefined,
  backendDuration?: number,
  // The run waits for the user (an approval); the timer stops and resumes without counting the wait.
  paused = false,
): number {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [trackedStart, setTrackedStart] = useState(startTime);
  const pausedMsRef = useRef(0);
  const pauseStartedRef = useRef<number | null>(null);

  // A backend duration freezes the timer, so don't run it once one is present.
  const shouldRunTimer =
    isStreaming && backendDuration === undefined && !paused;

  useEffect(() => {
    if (paused) {
      pauseStartedRef.current = Date.now();
    } else if (pauseStartedRef.current !== null) {
      pausedMsRef.current += Date.now() - pauseStartedRef.current;
      pauseStartedRef.current = null;
    }
  }, [paused]);

  // A new stream starts with no paused time.
  useEffect(() => {
    pausedMsRef.current = 0;
  }, [startTime]);

  // A new startTime is a new stream: reset now (adjust-state-during-render) so we never carry the
  // previous stream's elapsed — including when the timer isn't running and the effect won't reconcile.
  if (startTime !== trackedStart) {
    setTrackedStart(startTime);
    setElapsedSeconds(0);
  }

  useEffect(() => {
    if (!shouldRunTimer || !startTime) {
      return;
    }

    const updateElapsed = () => {
      const elapsed = Math.floor(
        (Date.now() - startTime - pausedMsRef.current) / 1000,
      );
      setElapsedSeconds((prev) => (prev === elapsed ? prev : elapsed));
    };

    updateElapsed();
    const intervalId = setInterval(updateElapsed, DURATION_TICK_MS);
    return () => clearInterval(intervalId);
  }, [shouldRunTimer, startTime]);

  if (backendDuration !== undefined) {
    return backendDuration;
  }
  // No start time → 0; a paused timer (startTime unchanged) keeps its last value.
  if (!startTime) {
    return 0;
  }
  return elapsedSeconds;
}
