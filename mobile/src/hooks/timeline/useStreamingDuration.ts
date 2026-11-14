// Live elapsed-seconds timer for the streaming header. Port of web's useStreamingDuration, with the
// RAF loop swapped for a setInterval poll — deterministic under jest fake timers, and RN gains
// nothing from RAF here.

import { type RefObject, useEffect, useState } from "react";

// Poll faster than 1s so the whole-second boundary stays crisp (web's RAF was ~16ms).
const DURATION_TICK_MS = 250;

// Time a stream spends waiting for the user (an approval), which the timer does not count.
export interface ExcludedWait {
  // Finished waits, in ms.
  totalMs: number;
  // Epoch ms the current wait started; null while the run works.
  since: number | null;
}

export function useStreamingDuration(
  isStreaming: boolean,
  startTime: number | undefined,
  backendDuration?: number,
  // Read on each tick, so a wait holds the value without re-rendering the owner.
  excludedWait?: RefObject<ExcludedWait>,
): number {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [trackedStart, setTrackedStart] = useState(startTime);

  // A backend duration freezes the timer, so don't run it once one is present.
  const shouldRunTimer = isStreaming && backendDuration === undefined;

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
      const wait = excludedWait?.current;
      const elapsed = Math.floor(
        ((wait?.since ?? Date.now()) - startTime - (wait?.totalMs ?? 0)) / 1000,
      );
      setElapsedSeconds((prev) => (prev === elapsed ? prev : elapsed));
    };

    updateElapsed();
    const intervalId = setInterval(updateElapsed, DURATION_TICK_MS);
    return () => clearInterval(intervalId);
  }, [shouldRunTimer, startTime, excludedWait]);

  if (backendDuration !== undefined) {
    return backendDuration;
  }
  // No start time → 0; a stopped timer (startTime unchanged) keeps its last value.
  if (!startTime) {
    return 0;
  }
  return elapsedSeconds;
}
