import { MutableRefObject } from "react";

/**
 * Clears multiple timeout refs and optionally resets them to null.
 * Returns true if any timeout was cleared.
 */
export function clearTimeoutRefs(
  timeoutRefs: Array<MutableRefObject<NodeJS.Timeout | null>>,
  resetToNull: boolean = false
): boolean {
  let hadPendingTimeout = false;

  for (const ref of timeoutRefs) {
    if (ref.current) {
      clearTimeout(ref.current);
      hadPendingTimeout = true;
      if (resetToNull) {
        ref.current = null;
      }
    }
  }

  return hadPendingTimeout;
}
