"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";

/**
 * Shared wide chat state: when on, chat messages and the input bar widen from
 * the reading width to the wide width (`--width-chat-wide-max`), centered.
 * Lives in context so the Appearance setting and the chat page stay in sync.
 * Persists per-browser in localStorage; starts false and hydrates in an effect
 * so SSR and the first client render agree.
 */
// Browsers store the choice under this key.
const STORAGE_KEY = "onyx:fullWidthChat";

interface WideChatContextValue {
  wideChat: boolean;
  setWideChat: (enabled: boolean) => void;
}

const WideChatContext = createContext<WideChatContextValue | null>(null);

interface WideChatProviderProps {
  children: React.ReactNode;
}

export function WideChatProvider({ children }: WideChatProviderProps) {
  const [wideChat, setWideChatState] = useState(false);

  useEffect(() => {
    try {
      setWideChatState(localStorage.getItem(STORAGE_KEY) === "true");
    } catch {
      // Storage may be unavailable (e.g. private browsing); keep the default.
    }
  }, []);

  const setWideChat = useCallback((enabled: boolean) => {
    setWideChatState(enabled);
    try {
      localStorage.setItem(STORAGE_KEY, String(enabled));
    } catch {
      // Persisting is best-effort. The setting still applies for this session.
    }
  }, []);

  return (
    <WideChatContext.Provider value={{ wideChat, setWideChat }}>
      {children}
    </WideChatContext.Provider>
  );
}

export function useWideChat(): WideChatContextValue {
  const ctx = useContext(WideChatContext);
  if (!ctx) {
    throw new Error("useWideChat must be used within a WideChatProvider");
  }
  return ctx;
}
