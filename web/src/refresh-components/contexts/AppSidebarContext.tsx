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

function setCollapsedCookie(collapsed: boolean) {
  const collapsedAsString = collapsed.toString();
  Cookies.set(SIDEBAR_TOGGLED_COOKIE_NAME, collapsedAsString, {
    expires: 365,
  });
  if (typeof window !== "undefined") {
    localStorage.setItem(SIDEBAR_TOGGLED_COOKIE_NAME, collapsedAsString);
  }
}

export interface AppSidebarProviderProps {
  collapsed: boolean;
  children: ReactNode;
}

export function AppSidebarProvider({
  collapsed: initiallyCollapsed,
  children,
}: AppSidebarProviderProps) {
  const [collapsed, setCollapsedInternal] = useState(initiallyCollapsed);

  const setCollapsed: Dispatch<SetStateAction<boolean>> = (value) => {
    setCollapsedInternal((prev) => {
      const newState = typeof value === "function" ? value(prev) : value;
      setCollapsedCookie(newState);
      return newState;
    });
  };

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const isMac = navigator.userAgent.toLowerCase().includes("mac");
      const isModifierPressed = isMac ? event.metaKey : event.ctrlKey;
      if (!isModifierPressed || event.key !== "e") return;

      event.preventDefault();
      setCollapsed((prev) => !prev);
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  return (
    <AppSidebarContext.Provider
      value={{
        collapsed,
        setCollapsed,
      }}
    >
      {children}
    </AppSidebarContext.Provider>
  );
}

export interface AppSidebarContextType {
  collapsed: boolean;
  setCollapsed: Dispatch<SetStateAction<boolean>>;
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
