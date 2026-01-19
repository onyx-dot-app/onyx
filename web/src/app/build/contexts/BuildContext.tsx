"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useMemo,
  type ReactNode,
} from "react";

/**
 * Build UI Context
 *
 * This context ONLY manages UI state (sidebar visibility, panel states).
 */
interface BuildContextValue {
  // UI state - left sidebar
  leftSidebarFolded: boolean;
  setLeftSidebarFolded: React.Dispatch<React.SetStateAction<boolean>>;

  // UI state - output panel (right side)
  outputPanelOpen: boolean;
  setOutputPanelOpen: (open: boolean) => void;
  toggleOutputPanel: () => void;
}

const BuildContext = createContext<BuildContextValue | null>(null);

export interface BuildProviderProps {
  children: ReactNode;
}

export function BuildProvider({ children }: BuildProviderProps) {
  // UI state - left sidebar
  const [leftSidebarFolded, setLeftSidebarFolded] = useState(false);

  // UI state - output panel (open by default when session exists)
  const [outputPanelOpen, setOutputPanelOpen] = useState(true);

  const toggleOutputPanel = useCallback(() => {
    setOutputPanelOpen((prev) => !prev);
  }, []);

  const value = useMemo<BuildContextValue>(
    () => ({
      leftSidebarFolded,
      setLeftSidebarFolded,
      outputPanelOpen,
      setOutputPanelOpen,
      toggleOutputPanel,
    }),
    [leftSidebarFolded, outputPanelOpen, toggleOutputPanel]
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
