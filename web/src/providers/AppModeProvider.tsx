"use client";

import { createContext, useContext } from "react";
import { eeGated } from "@/ce";
import { EEAppModeProvider } from "@/ee/providers/AppModeProvider";

export type AppMode = "auto" | "search" | "chat";

interface AppModeContextValue {
  appMode: AppMode;
  setAppMode: (mode: AppMode) => void;
}

export const AppModeContext = createContext<AppModeContextValue>({
  appMode: "chat",
  setAppMode: () => {},
});

export function useAppMode(): AppModeContextValue {
  return useContext(AppModeContext);
}

export const AppModeProvider = eeGated(EEAppModeProvider);
