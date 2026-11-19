"use client";

import { useEffect, useState } from "react";

/** `value`, once it has held still for `delayMs`. */
export default function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  // oxlint-disable-next-line anti-slop/no-unreasoned-state-sync -- debounce timer that publishes the value after delayMs
  useEffect(() => {
    const timeout = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timeout);
  }, [value, delayMs]);
  return debounced;
}
