/**
 * Pure numeric helpers. No platform APIs (no DOM, Node, or React) — safe to run
 * identically in a browser, Node, and React Native's Hermes engine.
 */

/** Clamp `value` into the inclusive range [`min`, `max`]. */
export function clamp(value: number, min: number, max: number): number {
  if (min > max) {
    throw new Error(`clamp: min (${min}) must be <= max (${max})`);
  }
  return Math.min(Math.max(value, min), max);
}

/** Round `value` to `decimals` decimal places. */
export function roundTo(value: number, decimals = 0): number {
  const factor = 10 ** decimals;
  // Nudge by EPSILON before scaling so values like 1.005 round to 1.01 rather
  // than 1 (binary float can't represent 1.005 exactly).
  return Math.round((value + Number.EPSILON) * factor) / factor;
}
