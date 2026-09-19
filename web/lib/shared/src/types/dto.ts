/**
 * Common data-transfer shapes used "across methods" by both web and mobile data
 * layers, so each platform consumes the same contract for the same backend data.
 */

/** A single page of a cursor-paginated collection. */
export interface Page<T> {
  items: T[];
  nextCursor?: string;
}

/** Result of an operation that can fail without throwing. */
export type Result<T, E = string> =
  | { ok: true; value: T }
  | { ok: false; error: E };
