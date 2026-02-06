"use client";

import React, { useState, useCallback } from "react";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { AppModeContext, AppMode } from "@/providers/AppModeProvider";

export interface AppModeProviderProps {
  children: React.ReactNode;
  /** Initial mode (defaults to "auto") */
  defaultMode?: AppMode;
}

/**
 * Provider for application mode (Auto/Search/Chat).
 *
 * This controls how user queries are handled:
 * - **auto**: Uses LLM classification to determine if query is search or chat
 * - **search**: Forces search mode - quick document lookup
 * - **chat**: Forces chat mode - conversation with follow-up questions
 */
export function AppModeProvider({
  children,
  defaultMode = "auto",
}: AppModeProviderProps) {
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();
  const [appMode, setAppModeState] = useState<AppMode>(
    isPaidEnterpriseFeaturesEnabled ? defaultMode : "chat"
  );

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
