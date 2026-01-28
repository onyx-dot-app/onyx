/**
 * AppModeProvider - Application Mode Context
 *
 * This provider manages the global application mode state, which determines how
 * user queries are processed in the unified search and chat experience.
 *
 * ## Modes
 *
 * - **auto**: The default mode. Uses LLM-based classification to automatically
 *   determine whether a user's query should trigger a search flow (quick document
 *   lookup) or a chat flow (conversational interaction with follow-ups).
 *
 * - **search**: Forces all queries into search mode. Bypasses classification and
 *   immediately performs document search, returning quick results with snippets
 *   and citations. Best for users who know they want to find specific documents.
 *
 * - **chat**: Forces all queries into chat mode. Bypasses classification and
 *   initiates a conversational interaction where the AI can ask follow-up questions,
 *   provide detailed explanations, and maintain context across multiple turns.
 *
 * ## Usage
 *
 * The mode is selected via a dropdown in the AppHeader (top-left of the page).
 * Components can read and update the mode using the `useAppMode` hook:
 *
 * ```tsx
 * import { useAppMode } from "@/providers/AppModeProvider";
 *
 * function MyComponent() {
 *   const { appMode, setAppMode } = useAppMode();
 *
 *   if (appMode === "search") {
 *     // Render search-optimized UI
 *   }
 * }
 * ```
 *
 * ## Architecture
 *
 * This provider is composed into the app via `AppProvider` and is available
 * throughout the entire application. The state is client-side only and resets
 * to "auto" on page refresh.
 */
"use client";

import React, { createContext, useContext, useState, useCallback } from "react";

export type AppMode = "auto" | "search" | "chat";

interface AppModeContextValue {
  /** Current application mode */
  appMode: AppMode;
  /** Update the application mode */
  setAppMode: (mode: AppMode) => void;
}

const AppModeContext = createContext<AppModeContextValue | null>(null);

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
  const [appMode, setAppModeState] = useState<AppMode>(defaultMode);

  const setAppMode = useCallback((mode: AppMode) => {
    setAppModeState(mode);
  }, []);

  return (
    <AppModeContext.Provider value={{ appMode, setAppMode }}>
      {children}
    </AppModeContext.Provider>
  );
}

/**
 * Hook to access the current app mode and setter.
 *
 * @example
 * ```tsx
 * const { appMode, setAppMode } = useAppMode();
 *
 * // Check current mode
 * if (appMode === "search") {
 *   // Handle search flow
 * }
 *
 * // Change mode
 * setAppMode("chat");
 * ```
 */
export function useAppMode(): AppModeContextValue {
  const context = useContext(AppModeContext);
  if (!context) {
    throw new Error("useAppMode must be used within an AppModeProvider");
  }
  return context;
}
