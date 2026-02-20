"use client";

import React, { useState, useCallback } from "react";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { AppModeContext, AppMode } from "@/providers/AppModeProvider";
import { useUser } from "@/providers/UserProvider";

export interface AppModeProviderProps {
  children: React.ReactNode;
}

/**
 * Provider for application mode (Search/Chat).
 *
 * This controls how user queries are handled:
 * - **search**: Forces search mode - quick document lookup
 * - **chat**: Forces chat mode - conversation with follow-up questions
 *
 * The initial mode is read from the user's persisted `default_app_mode` preference.
 */
export function AppModeProvider({ children }: AppModeProviderProps) {
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();
  const { user } = useUser();

  const persistedMode = user?.preferences?.default_app_mode;
  const initialMode: AppMode =
    isPaidEnterpriseFeaturesEnabled && persistedMode
      ? (persistedMode.toLowerCase() as AppMode)
      : "chat";

  const [appMode, setAppModeState] = useState<AppMode>(initialMode);

  const setAppMode = useCallback(
    (mode: AppMode) => {
      if (!isPaidEnterpriseFeaturesEnabled) return;
      setAppModeState(mode);
    },
    [isPaidEnterpriseFeaturesEnabled]
  );

  return (
    <AppModeContext.Provider value={{ appMode, setAppMode }}>
      {children}
    </AppModeContext.Provider>
  );
}
