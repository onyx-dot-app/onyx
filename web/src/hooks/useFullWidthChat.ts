import { useCallback, useState } from "react";

/**
 * Persisted (per-browser) toggle for full-width chat: when on, the message
 * column drops its reading-width cap and flows to the window width.
 * Client-only via localStorage.
 */
const STORAGE_KEY = "onyx:fullWidthChat";

export function useFullWidthChat() {
  const [fullWidthChat, setFullWidthChat] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem(STORAGE_KEY) === "true";
  });

  const toggleFullWidthChat = useCallback(() => {
    setFullWidthChat((prev) => {
      const next = !prev;
      if (typeof window !== "undefined") {
        localStorage.setItem(STORAGE_KEY, String(next));
      }
      return next;
    });
  }, []);

  return { fullWidthChat, toggleFullWidthChat };
}
