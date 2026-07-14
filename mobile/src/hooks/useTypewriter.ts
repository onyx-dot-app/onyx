// Paced character reveal for the streaming "typewriter" feel — ported from web's
// hooks/useTypewriter.ts. Decouples what's shown from how fast/bursty tokens actually arrive:
// reveals `target` a few chars per frame so a fast or chunked response still animates in. Pure
// React + requestAnimationFrame; the only platform swap from web is AppState (RN) in place of
// document.visibilitychange for the return-to-foreground snap.
import { useEffect, useMemo, useRef, useState } from "react";
import { AppState } from "react-native";

// Mid-stream reveal rate, in chars per 60fps frame. 3 ≈ 180 cps.
const CHARS_PER_FRAME = 3;
// Once the stream is finished, the rate becomes adaptive so a long backlog drains within
// ~CATCHUP_FRAMES frames — bursty rendering after the final packet is fine (the user is reading
// along, not watching new content arrive).
const CATCHUP_FRAMES = 30;

export interface UseTypewriterResult {
  displayed: string;
  // True while the post-finish adaptive drain is running (callers can pause auto-scroll).
  isDraining: boolean;
}

/**
 * Reveals `target` one chunk at a time on each animation frame. When `enabled` is false
 * (historical messages) it snaps to full on mount. The rAF loop pauses once caught up and resumes
 * when `target` grows. `streamFinished` lets it drain a bursty backlog faster once the backend is
 * done, so callers gating on "fully displayed" don't sit on a long tail.
 */
export function useTypewriter(
  target: string,
  enabled: boolean,
  streamFinished: boolean = false,
): UseTypewriterResult {
  // Latest inputs mirrored so the long-lived rAF loop reads them without restarting. Synced in an
  // effect (not written during render) to satisfy react-hooks/refs; a one-frame lag is invisible.
  const targetRef = useRef(target);
  const enabledRef = useRef(enabled);
  const streamFinishedRef = useRef(streamFinished);
  useEffect(() => {
    targetRef.current = target;
    enabledRef.current = enabled;
    streamFinishedRef.current = streamFinished;
  });

  // Captured once when the post-finish drain begins so the per-frame step stays constant instead
  // of decaying with the shrinking backlog (dividing the current backlog each tick overshoots).
  const drainStepRef = useRef<number | null>(null);

  const [isDraining, setIsDraining] = useState(false);
  const isDrainingRef = useRef(false);

  const [displayedLength, setDisplayedLength] = useState<number>(
    enabled ? 0 : target.length,
  );
  const displayedLengthRef = useRef(displayedLength);

  // Clamp (not reset) on target shrink — preserves already-revealed chars across cancel/regenerate.
  const prevTargetLengthRef = useRef(target.length);
  useEffect(() => {
    if (target.length < prevTargetLengthRef.current) {
      const clamped = Math.min(displayedLengthRef.current, target.length);
      displayedLengthRef.current = clamped;
      setDisplayedLength(clamped);
    }
    prevTargetLengthRef.current = target.length;
  }, [target.length]);

  // Self-scheduling rAF loop; pauses when caught up so idle/historical messages don't run forever.
  const rafIdRef = useRef<number | null>(null);
  const runningRef = useRef(false);
  const startLoopRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    const tick = () => {
      const targetLen = targetRef.current.length;
      const prev = displayedLengthRef.current;
      if (prev >= targetLen) {
        runningRef.current = false;
        rafIdRef.current = null;
        if (isDrainingRef.current) {
          isDrainingRef.current = false;
          setIsDraining(false);
        }
        return;
      }
      let charsThisFrame: number;
      if (streamFinishedRef.current) {
        if (drainStepRef.current === null) {
          const initialBacklog = targetLen - prev;
          drainStepRef.current = Math.max(
            CHARS_PER_FRAME,
            Math.ceil(initialBacklog / CATCHUP_FRAMES),
          );
          if (!isDrainingRef.current) {
            isDrainingRef.current = true;
            setIsDraining(true);
          }
        }
        charsThisFrame = drainStepRef.current;
      } else {
        charsThisFrame = CHARS_PER_FRAME;
      }
      const next = Math.min(prev + charsThisFrame, targetLen);
      displayedLengthRef.current = next;
      setDisplayedLength(next);
      rafIdRef.current = requestAnimationFrame(tick);
    };

    const start = () => {
      if (runningRef.current) return;
      // Animation disabled — snap to full and stay idle (history/hydrated messages).
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

  // Returning to the foreground snaps to full so the user sees the whole response immediately.
  useEffect(() => {
    const sub = AppState.addEventListener("change", (state) => {
      if (state === "active") {
        const targetLen = targetRef.current.length;
        if (displayedLengthRef.current < targetLen) {
          displayedLengthRef.current = targetLen;
          setDisplayedLength(targetLen);
        }
      }
    });
    return () => sub.remove();
  }, []);

  const displayed = useMemo(
    () => target.slice(0, Math.min(displayedLength, target.length)),
    [target, displayedLength],
  );

  return { displayed, isDraining };
}
