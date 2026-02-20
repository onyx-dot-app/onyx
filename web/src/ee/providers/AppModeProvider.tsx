"use client";

import React, { useState, useCallback } from "react";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { AppModeContext, AppMode } from "@/providers/AppModeProvider";
import { useUser } from "@/providers/UserProvider";
import { useSettingsContext } from "@/providers/SettingsProvider";

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
 * When search mode is unavailable (admin setting or no connectors), the mode is locked to "chat".
 */
export function AppModeProvider({ children }: AppModeProviderProps) {
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();
  const { user } = useUser();
  const settings = useSettingsContext();
  const { isSearchModeAvailable } = settings;

  const persistedMode = user?.preferences?.default_app_mode;
  const initialMode: AppMode =
    isPaidEnterpriseFeaturesEnabled && isSearchModeAvailable && persistedMode
      ? (persistedMode.toLowerCase() as AppMode)
      : "chat";

  const [appMode, setAppModeState] = useState<AppMode>(initialMode);

  const setAppMode = useCallback(
    (mode: AppMode) => {
      if (!isPaidEnterpriseFeaturesEnabled || !isSearchModeAvailable) return;
      setAppModeState(mode);
    },
    [isPaidEnterpriseFeaturesEnabled, isSearchModeAvailable]
  );

  return (
    <AppModeContext.Provider value={{ appMode, setAppMode }}>
      {children}
    </AppModeContext.Provider>
  );
}
