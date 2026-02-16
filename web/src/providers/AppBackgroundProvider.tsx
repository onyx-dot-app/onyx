"use client";

import React, { createContext, useContext, useMemo } from "react";
import { useUser } from "@/providers/UserProvider";
import {
  CHAT_BACKGROUND_NONE,
  getBackgroundById,
  ChatBackgroundOption,
} from "@/lib/constants/chatBackgrounds";

interface AppBackgroundContextType {
  /** The full background option object, or undefined if none/invalid */
  appBackground: ChatBackgroundOption | undefined;
  /** The URL of the background image, or null if no background is set */
  appBackgroundUrl: string | null;
  /** Whether a background is currently active */
  hasBackground: boolean;
}

const AppBackgroundContext = createContext<
  AppBackgroundContextType | undefined
>(undefined);

export function AppBackgroundProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user } = useUser();

  const value = useMemo(() => {
    const chatBackgroundId = user?.preferences?.chat_background;
    const appBackground = getBackgroundById(chatBackgroundId ?? null);
    const hasBackground =
      !!appBackground && appBackground.src !== CHAT_BACKGROUND_NONE;
    const appBackgroundUrl = hasBackground ? appBackground.src : null;

    return {
      appBackground,
      appBackgroundUrl,
      hasBackground,
    };
  }, [user?.preferences?.chat_background]);

  return (
    <AppBackgroundContext.Provider value={value}>
      {children}
    </AppBackgroundContext.Provider>
  );
}

export function useAppBackground() {
  const context = useContext(AppBackgroundContext);
  if (context === undefined) {
    throw new Error(
      "useAppBackground must be used within an AppBackgroundProvider"
    );
  }
  return context;
}
