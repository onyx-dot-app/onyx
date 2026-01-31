"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Throttle a rapidly changing value to at most one update per `intervalMs`.
 *
 * Useful when upstream changes are very frequent (e.g. per animation frame),
 * but downstream work is expensive (e.g. markdown parsing / syntax highlight).
 */
export function useThrottledValue<T>(value: T, intervalMs: number): T {
  const [throttledValue, setThrottledValue] = useState<T>(value);

  const lastEmittedAtRef = useRef<number>(0);
  const pendingValueRef = useRef<T>(value);
  const timeoutRef = useRef<number | null>(null);

  useEffect(() => {
    pendingValueRef.current = value;

    // If throttling is disabled, always emit immediately.
    if (intervalMs <= 0) {
      if (timeoutRef.current != null) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
      lastEmittedAtRef.current = Date.now();
      setThrottledValue(value);
      return;
    }

    const now = Date.now();
    const elapsed = now - lastEmittedAtRef.current;

    // If we've waited long enough, emit immediately.
    if (elapsed >= intervalMs) {
      if (timeoutRef.current != null) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
      lastEmittedAtRef.current = now;
      setThrottledValue(value);
      return;
    }

    // Otherwise schedule a trailing emit (latest value wins).
    if (timeoutRef.current != null) {
      return;
    }

    const waitMs = Math.max(0, intervalMs - elapsed);
    timeoutRef.current = setTimeout(() => {
      timeoutRef.current = null;
      lastEmittedAtRef.current = Date.now();
      setThrottledValue(pendingValueRef.current);
    }, waitMs) as unknown as number;
  }, [value, intervalMs]);

  useEffect(() => {
    return () => {
      if (timeoutRef.current != null) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
    };
  }, []);

  return throttledValue;
}
