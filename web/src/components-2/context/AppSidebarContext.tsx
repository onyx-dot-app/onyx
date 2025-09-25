"use client";

import React, {
  createContext,
  useContext,
  useState,
  ReactNode,
  Dispatch,
  SetStateAction,
  useEffect,
} from "react";
import Cookies from "js-cookie";
import { SIDEBAR_TOGGLED_COOKIE_NAME } from "@/components/resizable/constants";

function setFoldedState(folded: boolean) {
  const foldedAsString = folded.toString();
  Cookies.set(SIDEBAR_TOGGLED_COOKIE_NAME, foldedAsString, { expires: 365 });
  if (typeof window !== "undefined") {
    localStorage.setItem(SIDEBAR_TOGGLED_COOKIE_NAME, foldedAsString);
  }
}

export interface AppSidebarProviderProps {
  folded: boolean;
  children: ReactNode;
}

export function AppSidebarProvider({
  folded: initiallyFolded,
  children,
}: AppSidebarProviderProps) {
  const [folded, setFolded] = useState(() => {
    setFoldedState(initiallyFolded);
    return initiallyFolded;
  });

  const [hovered, setHovered] = useState(false);

  useEffect(() => {
    setFoldedState(folded);
  }, [folded]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const isMac = navigator.userAgent.toLowerCase().includes("mac");
      const isModifierPressed = isMac ? event.metaKey : event.ctrlKey;
      if (!isModifierPressed || event.key !== "e") return;

      event.preventDefault();
      setFolded((prev) => {
        const newState = !prev;
        setFoldedState(newState);
        return newState;
      });
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  return (
    <AppSidebarContext.Provider
      value={{
        folded,
        setFolded,
        foldedAndHovered: folded && hovered,
        setHovered,
      }}
    >
      {children}
    </AppSidebarContext.Provider>
  );
}

export interface AppSidebarContextType {
  folded: boolean;
  setFolded: Dispatch<SetStateAction<boolean>>;
  foldedAndHovered: boolean;
  setHovered: Dispatch<SetStateAction<boolean>>;
}

const AppSidebarContext = createContext<AppSidebarContextType | undefined>(
  undefined
);

export function useAppSidebarContext() {
  const context = useContext(AppSidebarContext);
  if (context === undefined) {
    throw new Error(
      "useAppSidebarContext must be used within an AppSidebarProvider"
    );
  }
  return context;
}
