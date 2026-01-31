"use client";

import { useEffect, useMemo, useRef, useState } from "react";

export interface SteadyRevealOptions {
  /** Base reveal speed while streaming. */
  baseCharsPerSecond?: number;
  /**
   * Faster reveal speed used to catch up when stream ends or when backlog is large.
   * Should be significantly higher than baseCharsPerSecond.
   */
  catchUpCharsPerSecond?: number;
  /** If backlog exceeds this many chars, ramp up to catchUpCharsPerSecond. */
  backlogCatchUpThresholdChars?: number;
  /** Hard cap for chars revealed per animation frame (prevents big jumps on tab wake). */
  maxCharsPerFrame?: number;
  /** Reveal at least this many chars per frame when enabled (prevents stalling on tiny dt). */
  minCharsPerFrame?: number;
}

export interface SteadyRevealResult {
  /** Current revealed text (prefix of targetText). */
  revealedText: string;
  /** Current revealed length in chars. */
  revealedLength: number;
  /** True when revealedLength has reached targetText.length. */
  isCaughtUp: boolean;
}

const DEFAULTS: Required<SteadyRevealOptions> = {
  baseCharsPerSecond: 90,
  catchUpCharsPerSecond: 650,
  backlogCatchUpThresholdChars: 600,
  maxCharsPerFrame: 250,
  minCharsPerFrame: 1,
};

// Maximum delta time (ms) per frame to prevent large jumps when tab was inactive.
const MAX_FRAME_DT_MS = 250;

/**
 * Reveal a growing string at a steady, time-based pace.
 *
 * - Independent of packet arrival cadence.
 * - Uses requestAnimationFrame for smooth timing.
 * - Supports catch-up once stream ends (or backlog is large).
 */
export function useSteadyReveal(
  targetText: string,
  {
    enabled,
    isDone,
    options,
  }: {
    enabled: boolean;
    isDone: boolean;
    options?: SteadyRevealOptions;
  }
): SteadyRevealResult {
  const cfg = useMemo<Required<SteadyRevealOptions>>(
    () => ({
      baseCharsPerSecond:
        options?.baseCharsPerSecond ?? DEFAULTS.baseCharsPerSecond,
      catchUpCharsPerSecond:
        options?.catchUpCharsPerSecond ?? DEFAULTS.catchUpCharsPerSecond,
      backlogCatchUpThresholdChars:
        options?.backlogCatchUpThresholdChars ??
        DEFAULTS.backlogCatchUpThresholdChars,
      maxCharsPerFrame: options?.maxCharsPerFrame ?? DEFAULTS.maxCharsPerFrame,
      minCharsPerFrame: options?.minCharsPerFrame ?? DEFAULTS.minCharsPerFrame,
    }),
    [
      options?.baseCharsPerSecond,
      options?.catchUpCharsPerSecond,
      options?.backlogCatchUpThresholdChars,
      options?.maxCharsPerFrame,
      options?.minCharsPerFrame,
    ]
  );

  const [revealedLength, setRevealedLength] = useState(() =>
    enabled ? 0 : targetText.length
  );
  // Keep a ref in sync so the RAF tick can compute nextLen synchronously.
  const revealedLengthRef = useRef<number>(revealedLength);
  useEffect(() => {
    revealedLengthRef.current = revealedLength;
  }, [revealedLength]);

  const rafIdRef = useRef<number | null>(null);
  const lastTimeRef = useRef<number | null>(null);
  const prevTargetTextRef = useRef<string>(targetText);
  const targetTextRef = useRef<string>(targetText);

  useEffect(() => {
    targetTextRef.current = targetText;
  }, [targetText]);

  // Reset behavior when targetText changes significantly (e.g., switching messages).
  useEffect(() => {
    const prev = prevTargetTextRef.current;
    prevTargetTextRef.current = targetText;

    // If text shrinks, clamp revealed length.
    if (targetText.length < prev.length) {
      const next = Math.min(revealedLengthRef.current, targetText.length);
      revealedLengthRef.current = next;
      setRevealedLength(next);
      return;
    }

    // If the new text doesn't start with the old text, it's a new message—reset to 0.
    if (!targetText.startsWith(prev)) {
      const next = enabled ? 0 : targetText.length;
      revealedLengthRef.current = next;
      setRevealedLength(next);
    }
  }, [targetText, enabled]);

  // If disabled, immediately reveal all.
  useEffect(() => {
    if (!enabled) {
      const next = targetText.length;
      revealedLengthRef.current = next;
      setRevealedLength(next);
    }
  }, [enabled, targetText.length]);

  useEffect(() => {
    if (!enabled) {
      // Safety: stop any running raf.
      if (rafIdRef.current != null) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
      lastTimeRef.current = null;
      return;
    }

    const tick = (now: number) => {
      if (lastTimeRef.current == null) {
        lastTimeRef.current = now;
      }
      const dtMs = now - lastTimeRef.current;
      lastTimeRef.current = now;

      const targetLen = targetTextRef.current.length;
      const prevLen = revealedLengthRef.current;

      let nextLen = prevLen;
      if (prevLen < targetLen) {
        const backlog = targetLen - prevLen;
        const cps =
          isDone || backlog >= cfg.backlogCatchUpThresholdChars
            ? cfg.catchUpCharsPerSecond
            : cfg.baseCharsPerSecond;

        // Clamp dt to avoid giant jumps when tab was inactive.
        const clampedDtMs = Math.min(dtMs, MAX_FRAME_DT_MS);
        const idealAdvance = (clampedDtMs / 1000) * cps;
        const advance = Math.max(
          cfg.minCharsPerFrame,
          Math.min(cfg.maxCharsPerFrame, Math.floor(idealAdvance))
        );

        nextLen = Math.min(targetLen, prevLen + advance);
      }

      if (nextLen !== prevLen) {
        revealedLengthRef.current = nextLen;
        setRevealedLength(nextLen);
      }

      // If caught up, stop scheduling frames.
      // - If isDone: stop permanently (stream complete).
      // - If !isDone: pause until more content arrives. The effect will re-run
      //   when targetText.length changes (via dependency array), restarting the RAF.
      if (nextLen >= targetLen) {
        rafIdRef.current = null;
        lastTimeRef.current = null;
        return;
      }

      rafIdRef.current = requestAnimationFrame(tick);
    };

    rafIdRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafIdRef.current != null) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
      lastTimeRef.current = null;
    };
    // Note: targetText.length is in the dependency array so that when new content
    // arrives (and the RAF was paused because we were caught up), the effect
    // re-runs and restarts the animation loop.
  }, [
    enabled,
    isDone,
    targetText.length,
    cfg.baseCharsPerSecond,
    cfg.catchUpCharsPerSecond,
    cfg.backlogCatchUpThresholdChars,
    cfg.maxCharsPerFrame,
    cfg.minCharsPerFrame,
  ]);

  const safeLength = Math.min(revealedLength, targetText.length);
  const revealedText = useMemo(
    () => (safeLength > 0 ? targetText.slice(0, safeLength) : ""),
    [targetText, safeLength]
  );

  return {
    revealedText,
    revealedLength: safeLength,
    isCaughtUp: safeLength >= targetText.length,
  };
}

