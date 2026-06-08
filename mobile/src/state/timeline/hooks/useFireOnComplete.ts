// Fires onComplete() exactly once, the first time isComplete flips true.
import { useEffect, useRef } from "react";

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
