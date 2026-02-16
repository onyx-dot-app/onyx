"use client";

import {
  createContext,
  useContext,
  useState,
  useMemo,
  type ReactNode,
} from "react";

/**
 * Build UI Context
 *
 * This context manages UI state (sidebar visibility).
 * Output panel state is stored per-session in useBuildSessionStore.
 */
interface BuildContextValue {
  // UI state - left sidebar
  leftSidebarFolded: boolean;
  setLeftSidebarFolded: React.Dispatch<React.SetStateAction<boolean>>;
}

const BuildContext = createContext<BuildContextValue | null>(null);

export interface BuildProviderProps {
  children: ReactNode;
}

export function BuildProvider({ children }: BuildProviderProps) {
  const [leftSidebarFolded, setLeftSidebarFolded] = useState(false);

  const value = useMemo<BuildContextValue>(
    () => ({
      leftSidebarFolded,
      setLeftSidebarFolded,
    }),
    [leftSidebarFolded]
  );

  return (
    <BuildContext.Provider value={value}>{children}</BuildContext.Provider>
  );
}

export function useBuildContext() {
  const context = useContext(BuildContext);
  if (!context) {
    throw new Error("useBuildContext must be used within a BuildProvider");
  }
  return context;
}
