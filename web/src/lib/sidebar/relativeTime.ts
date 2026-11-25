import { useSyncExternalStore } from "react";

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

export type ElapsedUnit = "minute" | "hour" | "day";

export interface ElapsedTime {
  value: number;
  unit: ElapsedUnit;
}

/** The elapsed time at T3's precision, or null for under a minute. */
export function compactElapsed(
  timestamp: string,
  nowMs: number
): ElapsedTime | null {
  const updatedMs = Date.parse(timestamp);
  if (Number.isNaN(updatedMs)) return null;
  const elapsedMs = Math.max(0, nowMs - updatedMs);
  if (elapsedMs < MINUTE_MS) return null;
  if (elapsedMs < HOUR_MS)
    return { value: Math.floor(elapsedMs / MINUTE_MS), unit: "minute" };
  if (elapsedMs < DAY_MS)
    return { value: Math.floor(elapsedMs / HOUR_MS), unit: "hour" };
  return { value: Math.floor(elapsedMs / DAY_MS), unit: "day" };
}

const listeners = new Set<() => void>();
let timer: ReturnType<typeof setInterval> | null = null;

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (timer === null) {
    timer = setInterval(() => {
      listeners.forEach((notify) => notify());
    }, MINUTE_MS);
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  };
}

function currentMinute(): number {
  return Math.floor(Date.now() / MINUTE_MS) * MINUTE_MS;
}

/** The current minute. One shared timer ticks every row. */
export function useNowMinute(): number {
  return useSyncExternalStore(subscribe, currentMinute, currentMinute);
}
