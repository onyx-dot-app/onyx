/**
 * Pure formatting helpers. No platform APIs — see ./numbers for the constraint.
 */

const BYTE_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"] as const;

/** Human-readable byte size, e.g. `formatBytes(1536)` -> `"1.5 KB"`. */
export function formatBytes(bytes: number, decimals = 1): string {
  if (bytes < 0) {
    throw new Error(`formatBytes: bytes (${bytes}) must be >= 0`);
  }
  if (bytes === 0) {
    return "0 B";
  }
  const exponent = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    BYTE_UNITS.length - 1
  );
  const value = bytes / 1024 ** exponent;
  const rounded = Number(value.toFixed(decimals));
  return `${rounded} ${BYTE_UNITS[exponent]}`;
}

/**
 * Truncate `input` to at most `max` characters (including the ellipsis).
 * When `max` is 0 the result is an empty string.
 */
export function truncate(input: string, max: number): string {
  if (max < 0) {
    throw new Error(`truncate: max (${max}) must be >= 0`);
  }
  if (input.length <= max) {
    return input;
  }
  return max === 0 ? "" : `${input.slice(0, max - 1)}…`;
}
