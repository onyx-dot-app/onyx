import { useCallback, useEffect, useState } from "react";

/**
 * Persisted (per-browser) toggle for full-width chat: when on, the message
 * column drops its reading-width cap and flows to the window width. Starts
 * false and hydrates from localStorage in an effect so SSR and the first
 * client render agree (avoids a hydration mismatch / layout snap).
 */
const STORAGE_KEY = "onyx:fullWidthChat";

export function useFullWidthChat() {
  const [fullWidthChat, setFullWidthChat] = useState(false);

  useEffect(() => {
    setFullWidthChat(localStorage.getItem(STORAGE_KEY) === "true");
  }, []);

  const toggleFullWidthChat = useCallback(() => {
    setFullWidthChat((prev) => {
      const next = !prev;
      localStorage.setItem(STORAGE_KEY, String(next));
      return next;
    });
  }, []);

  return { fullWidthChat, toggleFullWidthChat };
}
