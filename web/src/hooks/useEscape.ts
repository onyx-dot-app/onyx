"use client";

import { useEffect } from "react";

/**
 * Custom hook that listens for the "Escape" key and calls the provided callback.
 *
 * @param callback - Function to call when the Escape key is pressed
 * @param enabled - Optional boolean to enable/disable the hook (defaults to true)
 */
export function useEscape(callback: () => void, enabled: boolean = true) {
  useEffect(() => {
    if (!enabled) return;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;

      event.preventDefault();
      callback();
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [callback, enabled]);
}
