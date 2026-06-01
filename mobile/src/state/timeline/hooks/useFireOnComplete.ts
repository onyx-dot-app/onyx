// useFireOnComplete.ts — fires `onComplete()` exactly once, the first time
// `isComplete` flips true.
//
// Extracted from the ~13 timeline renderers that each copy-pasted the same
// `useRef(false)` guard + `useEffect` that called `onComplete()` once on
// completion. Semantics are identical: a per-mount ref guard ensures the
// callback runs at most once, and the effect re-runs on `[isComplete,
// onComplete]` so a stable callback won't refire.

import { useEffect, useRef } from "react";

/**
 * Calls `onComplete` exactly once, the first time `isComplete` becomes true.
 *
 * @param isComplete - Whether the tool/step has reached its terminal state.
 * @param onComplete - Callback fired once on completion.
 */
export function useFireOnComplete(
  isComplete: boolean,
  onComplete?: () => void
): void {
  const firedRef = useRef(false);
  useEffect(() => {
    if (isComplete && !firedRef.current) {
      firedRef.current = true;
      onComplete?.();
    }
  }, [isComplete, onComplete]);
}
