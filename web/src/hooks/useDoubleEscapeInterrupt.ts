import { useCallback, useEffect, useRef, useState } from "react";

interface UseDoubleEscapeInterruptArgs {
  /** Only listen + arm while true (e.g. a response is streaming). */
  enabled: boolean;
  /** Fired on the second Esc within the window. */
  onInterrupt: () => void;
  /** Milliseconds the first Esc stays "armed" before disarming. */
  windowMs?: number;
}

/**
 * Double-Esc interrupt: the first Esc "arms" (returns `armed: true`) for a
 * short window; a second Esc within it fires `onInterrupt`. If the window
 * lapses, it disarms — no penalty. A single window-level listener handles
 * Esc whether or not the input has focus; gate it via `enabled` so popovers
 * (which consume Esc to close themselves) take precedence.
 */
export function useDoubleEscapeInterrupt({
  enabled,
  onInterrupt,
  windowMs = 1500,
}: UseDoubleEscapeInterruptArgs): { armed: boolean } {
  const [armed, setArmed] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Held in a ref so the listener doesn't tear down on onInterrupt identity churn.
  const onInterruptRef = useRef(onInterrupt);
  onInterruptRef.current = onInterrupt;

  const disarm = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setArmed(false);
  }, []);

  useEffect(() => {
    if (!enabled) {
      disarm();
      return;
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      // Ignore auto-repeat: holding Esc must not count as the second press.
      if (event.repeat) return;
      // A popover already handled Esc (e.g. closed a menu) — leave it alone.
      if (event.defaultPrevented || event.isComposing) return;

      event.preventDefault();
      if (timerRef.current !== null) {
        disarm();
        onInterruptRef.current();
      } else {
        setArmed(true);
        timerRef.current = setTimeout(() => {
          timerRef.current = null;
          setArmed(false);
        }, windowMs);
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      disarm();
    };
  }, [enabled, windowMs, disarm]);

  return { armed };
}
