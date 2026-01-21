"use client";

import React, { createContext, useContext, useState, useEffect } from "react";
import { useTheme } from "next-themes";
import { LocalStorageKeys } from "@/lib/extension/constants";
import { ThemePreference } from "@/lib/types";

interface NRFPreferencesContextValue {
  theme: ThemePreference;
  setTheme: (t: ThemePreference) => void;
  useOnyxAsNewTab: boolean;
  setUseOnyxAsNewTab: (v: boolean) => void;
}

const NRFPreferencesContext = createContext<
  NRFPreferencesContextValue | undefined
>(undefined);

function useLocalStorageState<T>(
  key: string,
  defaultValue: T
): [T, (value: T) => void] {
  const [state, setState] = useState<T>(() => {
    if (typeof window !== "undefined") {
      const storedValue = localStorage.getItem(key);
      return storedValue ? JSON.parse(storedValue) : defaultValue;
    }
    return defaultValue;
  });

  const setValue = (value: T) => {
    setState(value);
    if (typeof window !== "undefined") {
      localStorage.setItem(key, JSON.stringify(value));
    }
  };

  return [state, setValue];
}

export function NRFPreferencesProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const { setTheme: setNextThemesTheme } = useTheme();
  const [theme, setThemeState] = useLocalStorageState<ThemePreference>(
    LocalStorageKeys.THEME,
    ThemePreference.DARK
  );
  const [useOnyxAsNewTab, setUseOnyxAsNewTab] = useLocalStorageState<boolean>(
    LocalStorageKeys.USE_ONYX_AS_NEW_TAB,
    true
  );

  // Sync NRF theme with next-themes to enable Tailwind dark mode classes
  // This ensures the HTML element gets the 'dark' class for Tailwind dark: classes to work
  useEffect(() => {
    setNextThemesTheme(theme);
  }, [theme, setNextThemesTheme]);

  // Wrapper function to update both local state and next-themes
  const setTheme = (newTheme: ThemePreference) => {
    setThemeState(newTheme);
    setNextThemesTheme(newTheme);
  };

  return (
    <NRFPreferencesContext.Provider
      value={{
        theme,
        setTheme,
        useOnyxAsNewTab,
        setUseOnyxAsNewTab,
      }}
    >
      {children}
    </NRFPreferencesContext.Provider>
  );
}

export function useNRFPreferences() {
  const context = useContext(NRFPreferencesContext);
  if (!context) {
    throw new Error(
      "useNRFPreferences must be used within an NRFPreferencesProvider"
    );
  }
  return context;
}
