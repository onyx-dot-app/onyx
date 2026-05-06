import { useEffect, useMemo, useRef, useState } from "react";

// Fixed reveal rate — NOT adaptive. Any ceil(delta/N) formula produces
// visible chunks on burst packet arrivals. 1 = 60 cps, 2 = 120 cps.
const CHARS_PER_FRAME = 3;

/**
 * Reveals `target` one character at a time on each animation frame.
 * When `enabled` is false (historical messages), snaps to full on mount.
 * The rAF loop pauses once caught up and resumes when `target` grows.
 */
export function useTypewriter(target: string, enabled: boolean): string {
  // Ref so the rAF loop reads latest length without restarting.
  const targetRef = useRef(target);
  targetRef.current = target;

  // Mirror `enabled` so the restart effect can short-circuit when the
  // caller has turned animation off (e.g. voice-mode, where display is
  // driven by audio position — the typewriter must stay idle and not
  // animate a jump after audio ends).
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  // `enabled` controls initial state: animate from 0 vs snap to full for
  // history/voice. Transitions mid-stream are handled via enabledRef in
  // the restart effect so a flip to false doesn't dump the buffered tail
  // *and* doesn't spin up the rAF loop on later growth.
  const [displayedLength, setDisplayedLength] = useState<number>(
    enabled ? 0 : target.length
  );

  // Mirror displayedLength in a ref so the rAF loop can read the latest
  // value without stale-closure issues AND without needing a functional
  // state updater (which must be pure — no ref mutations inside).
  const displayedLengthRef = useRef(displayedLength);

  // Clamp (not reset) on target shrink — preserves already-revealed chars
  // across user-cancel freeze and regeneration.
  const prevTargetLengthRef = useRef(target.length);
  useEffect(() => {
    if (target.length < prevTargetLengthRef.current) {
      const clamped = Math.min(displayedLengthRef.current, target.length);
      displayedLengthRef.current = clamped;
      setDisplayedLength(clamped);
    }
    prevTargetLengthRef.current = target.length;
  }, [target.length]);

  // Self-scheduling rAF loop. Pauses when caught up so idle/historical
  // messages don't run a 60fps no-op updater for their entire lifetime.
  const rafIdRef = useRef<number | null>(null);
  const runningRef = useRef(false);
  const startLoopRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    const tick = () => {
      const targetLen = targetRef.current.length;
      const prev = displayedLengthRef.current;
      if (prev >= targetLen) {
        // Caught up — pause the loop. The sibling effect below will
        // restart it when `target` grows.
        runningRef.current = false;
        rafIdRef.current = null;
        return;
      }
      const next = Math.min(prev + CHARS_PER_FRAME, targetLen);
      displayedLengthRef.current = next;
      setDisplayedLength(next);
      rafIdRef.current = requestAnimationFrame(tick);
    };

    const start = () => {
      if (runningRef.current) return;
      // Animation disabled — snap to full and stay idle. This is the
      // voice-mode path where content is driven by audio position, and
      // any "gap" (e.g. user stops audio early) must jump instantly
      // instead of animating a 1500-char typewriter burst.
      if (!enabledRef.current) {
        const targetLen = targetRef.current.length;
        if (displayedLengthRef.current !== targetLen) {
          displayedLengthRef.current = targetLen;
          setDisplayedLength(targetLen);
        }
        return;
      }
      runningRef.current = true;
      rafIdRef.current = requestAnimationFrame(tick);
    };

    startLoopRef.current = start;

    if (targetRef.current.length > displayedLengthRef.current) {
      start();
    }

    return () => {
      runningRef.current = false;
      if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
      startLoopRef.current = null;
    };
  }, []);

  // Restart the loop when target grows past what's currently displayed.
  useEffect(() => {
    if (target.length > displayedLength && startLoopRef.current) {
      startLoopRef.current();
    }
  }, [target.length, displayedLength]);

  // When the user navigates away and back (tab switch, window focus),
  // snap to all collected content so they see the full response immediately.
  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === "visible") {
        const targetLen = targetRef.current.length;
        if (displayedLengthRef.current < targetLen) {
          displayedLengthRef.current = targetLen;
          setDisplayedLength(targetLen);
        }
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () =>
      document.removeEventListener("visibilitychange", handleVisibility);
  }, []);

  return useMemo(
    () => target.slice(0, Math.min(displayedLength, target.length)),
    [target, displayedLength]
  );
}
