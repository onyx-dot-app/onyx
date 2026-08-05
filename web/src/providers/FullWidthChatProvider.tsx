"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";

/**
 * Shared full-width chat state: when on, chat messages and the input bar drop
 * their reading-width cap and flow to the window width. Lives in context so the
 * top-bar toggle and the chat page stay in sync. Persists per-browser in
 * localStorage; starts false and hydrates in an effect so SSR and the first
 * client render agree.
 */
const STORAGE_KEY = "onyx:fullWidthChat";

interface FullWidthChatContextValue {
  fullWidthChat: boolean;
  toggleFullWidthChat: () => void;
}

const FullWidthChatContext = createContext<FullWidthChatContextValue | null>(
  null
);

interface FullWidthChatProviderProps {
  children: React.ReactNode;
}

export function FullWidthChatProvider({
  children,
}: FullWidthChatProviderProps) {
  const [fullWidthChat, setFullWidthChat] = useState(false);

  useEffect(() => {
    try {
      setFullWidthChat(localStorage.getItem(STORAGE_KEY) === "true");
    } catch {
      // Storage may be unavailable (e.g. private browsing); keep the default.
    }
  }, []);

  const toggleFullWidthChat = useCallback(() => {
    setFullWidthChat((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(STORAGE_KEY, String(next));
      } catch {
        // Persisting is best-effort; the toggle still flips for this session.
      }
      return next;
    });
  }, []);

  return (
    <FullWidthChatContext.Provider
      value={{ fullWidthChat, toggleFullWidthChat }}
    >
      {children}
    </FullWidthChatContext.Provider>
  );
}

export function useFullWidthChat(): FullWidthChatContextValue {
  const ctx = useContext(FullWidthChatContext);
  if (!ctx) {
    throw new Error(
      "useFullWidthChat must be used within a FullWidthChatProvider"
    );
  }
  return ctx;
}
