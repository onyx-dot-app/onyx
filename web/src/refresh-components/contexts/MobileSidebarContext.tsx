"use client";

import React, {
  createContext,
  useContext,
  useMemo,
  useState,
  PropsWithChildren,
} from "react";

interface MobileSidebarContextValue {
  isMobileSidebarOpen: boolean;
  openSidebar: () => void;
  closeSidebar: () => void;
  toggleSidebar: () => void;
}

const MobileSidebarContext = createContext<
  MobileSidebarContextValue | undefined
>(undefined);

export function MobileSidebarProvider({ children }: PropsWithChildren) {
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);

  const value = useMemo(
    () => ({
      isMobileSidebarOpen,
      openSidebar: () => setIsMobileSidebarOpen(true),
      closeSidebar: () => setIsMobileSidebarOpen(false),
      toggleSidebar: () => setIsMobileSidebarOpen((prev) => !prev),
    }),
    [isMobileSidebarOpen]
  );

  return (
    <MobileSidebarContext.Provider value={value}>
      {children}
    </MobileSidebarContext.Provider>
  );
}

export function useMobileSidebar() {
  const context = useContext(MobileSidebarContext);
  if (!context) {
    throw new Error(
      "useMobileSidebar must be used within a MobileSidebarProvider"
    );
  }
  return context;
}
