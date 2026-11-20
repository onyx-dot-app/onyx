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
 * Appearance setting and the chat page stay in sync. Persists per-browser in
 * localStorage; starts false and hydrates in an effect so SSR and the first
 * client render agree.
 */
const STORAGE_KEY = "onyx:fullWidthChat";

interface FullWidthChatContextValue {
  fullWidthChat: boolean;
  setFullWidthChat: (enabled: boolean) => void;
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
  const [fullWidthChat, setFullWidthChatState] = useState(false);

  useEffect(() => {
    try {
      setFullWidthChatState(localStorage.getItem(STORAGE_KEY) === "true");
    } catch {
      // Storage may be unavailable (e.g. private browsing); keep the default.
    }
  }, []);

  const setFullWidthChat = useCallback((enabled: boolean) => {
    setFullWidthChatState(enabled);
    try {
      localStorage.setItem(STORAGE_KEY, String(enabled));
    } catch {
      // Persisting is best-effort. The setting still applies for this session.
    }
  }, []);

  return (
    <FullWidthChatContext.Provider value={{ fullWidthChat, setFullWidthChat }}>
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
