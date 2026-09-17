"use client";

import { useCallback } from "react";

/**
 * Returns a stable callback ref that moves focus to the element when it mounts.
 *
 * Use this for inputs that only render after a user action (inline editors,
 * popover search fields, modal fields). The `autoFocus` attribute covers the
 * same case, but it also steals focus on page load, so it is disallowed.
 */
export default function useFocusOnMount<T extends HTMLElement>(
  enabled: boolean = true
): (element: T | null) => void {
  return useCallback(
    (element: T | null) => {
      if (enabled) element?.focus();
    },
    [enabled]
  );
}
