"use client";

import { CombinedSettings } from "@/app/admin/settings/interfaces";
import { createContext } from "react";

export const SettingsContext = createContext<CombinedSettings | null>(null);

export function SettingsProvider({
  children,
  settings,
}: {
  children: React.ReactNode | JSX.Element;
  settings: CombinedSettings;
}) {
  return (
    <SettingsContext.Provider value={settings}>
      {children}
    </SettingsContext.Provider>
  );
}
