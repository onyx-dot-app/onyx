"use client";

import { useEffect } from "react";

export function useKeyPress(
  callback: () => void,
  key: string,
  enabled: boolean = true
) {
  // useEffect(() => {
  //   if (!enabled) return;
  //   function handleKeyDown(event: KeyboardEvent) {
  //     if (event.key !== key) return;
  //     event.preventDefault();
  //     callback();
  //   }
  //   document.addEventListener("keydown", handleKeyDown);
  //   return () => {
  //     document.removeEventListener("keydown", handleKeyDown);
  //   };
  // }, [callback, enabled]);
}

/**
 * Custom hook that listens for the "Escape" key and calls the provided callback.
 *
 * @param callback - Function to call when the Escape key is pressed
 * @param enabled - Optional boolean to enable/disable the hook (defaults to true)
 */
export function useEscape(callback: () => void, enabled: boolean = true) {
  useKeyPress(callback, "Escape", enabled);
}

/**
 * Custom hook that listens for the "Enter" key and calls the provided callback.
 *
 * @param callback - Function to call when the Enter key is pressed
 * @param enabled - Optional boolean to enable/disable the hook (defaults to true)
 */
export function useEnter(callback: () => void, enabled: boolean = true) {
  useKeyPress(callback, "Enter", enabled);
}
