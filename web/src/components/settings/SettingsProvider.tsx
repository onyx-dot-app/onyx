"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { CombinedSettings } from "@/app/admin/settings/interfaces";

export interface SettingsProviderProps {
  children: React.ReactNode | JSX.Element;
  settings: CombinedSettings;
}

export function SettingsProvider({
  children,
  settings,
}: SettingsProviderProps) {
  const [isMobile, setIsMobile] = useState<boolean | undefined>();

  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth < 768);
    };

    checkMobile();
    window.addEventListener("resize", checkMobile);
    return () => window.removeEventListener("resize", checkMobile);
  }, []);

  return (
    <SettingsContext.Provider value={{ ...settings, isMobile }}>
      {children}
    </SettingsContext.Provider>
  );
}

export const SettingsContext = createContext<CombinedSettings | undefined>(
  undefined
);

export function useSettingsContext() {
  const context = useContext(SettingsContext);
  if (context === undefined) {
    throw new Error(
      "useSettingsContext must be used within an SettingsProvider"
    );
  }
  return context;
}
