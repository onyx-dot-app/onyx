"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  useMemo,
  type ReactNode,
} from "react";
import { VIDEO_BACKGROUND_STORAGE_KEY } from "@/app/craft/components/video-background/constants";

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
  videoBackgroundEnabled: boolean;
  toggleVideoBackground: () => void;
}

const BuildContext = createContext<BuildContextValue | null>(null);

export interface BuildProviderProps {
  children: ReactNode;
}

export function BuildProvider({ children }: BuildProviderProps) {
  const [leftSidebarFolded, setLeftSidebarFolded] = useState(false);
  const [videoBackgroundEnabled, setVideoBackgroundEnabled] = useState(false);

  useEffect(() => {
    setVideoBackgroundEnabled(
      localStorage.getItem(VIDEO_BACKGROUND_STORAGE_KEY) === "true"
    );
  }, []);

  const toggleVideoBackground = useCallback(() => {
    setVideoBackgroundEnabled((prev) => {
      const next = !prev;
      localStorage.setItem(VIDEO_BACKGROUND_STORAGE_KEY, String(next));
      return next;
    });
  }, []);

  const value = useMemo<BuildContextValue>(
    () => ({
      leftSidebarFolded,
      setLeftSidebarFolded,
      videoBackgroundEnabled,
      toggleVideoBackground,
    }),
    [leftSidebarFolded, videoBackgroundEnabled, toggleVideoBackground]
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
