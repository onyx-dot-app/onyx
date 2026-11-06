import { useEffect, useMemo, useRef, useState } from "react";

// Keep a short text buffer so packet bursts do not become visible pauses.
const SMOOTHING_WINDOW_MS = 200;
const MIN_CHARS_PER_SECOND = 30;
const FINISH_DRAIN_MS = 500;
const MAX_FRAME_MS = 50;

export interface UseTypewriterResult {
  displayed: string;
  /** True while post-finish adaptive drain is running. Callers can use
   *  this to pause auto-scroll so the page doesn't yank when the
   *  typewriter speeds up — the user is reading at this point, not
   *  watching new content arrive. */
  isDraining: boolean;
}

/**
 * Reveals `target` at a rate that follows the buffered text.
 * When `enabled` is false (historical messages), snaps to full on mount.
 * `visiblePrefixLength` skips animation for restored content.
 * The rAF loop pauses once caught up and resumes when `target` grows.
 *
 * `streamFinished` lets the loop drain any remaining backlog faster
 * once the backend is done, so callers gating on "FE fully displayed"
 * don't sit on a long tail when packets arrived in a burst.
 */
export function useTypewriter(
  target: string,
  enabled: boolean,
  streamFinished: boolean = false,
  visiblePrefixLength: number = 0
): UseTypewriterResult {
  // Ref so the rAF loop reads latest length without restarting.
  const targetRef = useRef(target);

  // Mirror `enabled` so the restart effect can short-circuit when the
  // caller has turned animation off (e.g. voice-mode, where display is
  // driven by audio position — the typewriter must stay idle and not
  // animate a jump after audio ends).
  const enabledRef = useRef(enabled);

  // Read inside the rAF loop without restarting it.
  const streamFinishedRef = useRef(streamFinished);

  useEffect(() => {
    targetRef.current = target;
    enabledRef.current = enabled;
    streamFinishedRef.current = streamFinished;
  }, [target, enabled, streamFinished]);

  // Fix the finishing rate once so the remaining tail drains in bounded time.
  const drainRateRef = useRef<number | null>(null);

  // Exposed so callers can suppress auto-scroll while the drain runs.
  const [isDraining, setIsDraining] = useState(false);
  const isDrainingRef = useRef(false);

  // Start after the restored prefix, or show all content for
  // history/voice. Transitions mid-stream are handled via enabledRef in
  // the restart effect so a flip to false doesn't dump the buffered tail
  // *and* doesn't spin up the rAF loop on later growth.
  const [displayedLength, setDisplayedLength] = useState<number>(
    enabled ? Math.min(visiblePrefixLength, target.length) : target.length
  );

  // Retain fractional progress between frames, including high-refresh displays.
  const displayedLengthRef = useRef(displayedLength);

  useEffect(() => {
    const visible = Math.min(visiblePrefixLength, target.length);
    if (displayedLengthRef.current < visible) {
      displayedLengthRef.current = visible;
      setDisplayedLength(visible);
    }
  }, [visiblePrefixLength, target.length]);

  // Clamp (not reset) on target shrink — preserves already-revealed chars
  // across user-cancel freeze and regeneration.
  const prevTargetLengthRef = useRef(target.length);
  useEffect(() => {
    if (target.length < prevTargetLengthRef.current) {
      const clamped = Math.min(displayedLengthRef.current, target.length);
      displayedLengthRef.current = clamped;
      setDisplayedLength(Math.floor(clamped));
    }
    prevTargetLengthRef.current = target.length;
  }, [target.length]);

  // Self-scheduling rAF loop. Pauses when caught up so idle/historical
  // messages don't run a 60fps no-op updater for their entire lifetime.
  const rafIdRef = useRef<number | null>(null);
  const runningRef = useRef(false);
  const startLoopRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    let lastFrameTime = performance.now();
    const tick = (now: number) => {
      const elapsed = Math.max(0, Math.min(now - lastFrameTime, MAX_FRAME_MS));
      lastFrameTime = now;
      const targetLen = targetRef.current.length;
      const prev = displayedLengthRef.current;
      if (prev >= targetLen) {
        // Caught up — pause the loop. The sibling effect below will
        // restart it when `target` grows.
        runningRef.current = false;
        rafIdRef.current = null;
        if (isDrainingRef.current) {
          isDrainingRef.current = false;
          setIsDraining(false);
        }
        return;
      }
      const remaining = targetLen - prev;
      let charsPerSecond: number;
      if (streamFinishedRef.current) {
        if (drainRateRef.current === null) {
          drainRateRef.current = Math.max(
            MIN_CHARS_PER_SECOND,
            (remaining * 1000) / FINISH_DRAIN_MS
          );
          if (!isDrainingRef.current) {
            isDrainingRef.current = true;
            setIsDraining(true);
          }
        }
        charsPerSecond = drainRateRef.current;
      } else {
        charsPerSecond = Math.max(
          MIN_CHARS_PER_SECOND,
          (remaining * 1000) / SMOOTHING_WINDOW_MS
        );
      }
      const next = Math.min(
        prev + (charsPerSecond * elapsed) / 1000,
        targetLen
      );
      displayedLengthRef.current = next;
      setDisplayedLength(Math.floor(next));
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
      lastFrameTime = performance.now();
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

  const displayed = useMemo(
    () => target.slice(0, Math.max(displayedLength, visiblePrefixLength)),
    [target, displayedLength, visiblePrefixLength]
  );

  return { displayed, isDraining };
}
