/**
 * Whether a backfill window starts at the Unix epoch: the backend's start for
 * a window that covers all history.
 */
export function windowCoversAllHistory(windowStart: string): boolean {
  return Date.parse(windowStart) <= 0;
}
