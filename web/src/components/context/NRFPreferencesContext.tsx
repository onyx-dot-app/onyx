"use client";

import React, { createContext, useContext, useState, useEffect } from "react";
import { useTheme } from "next-themes";
import { notifyExtensionOfThemeChange } from "@/lib/extension/utils";
import {
  darkExtensionImages,
  lightExtensionImages,
  LocalStorageKeys,
} from "@/lib/extension/constants";
import { ThemePreference } from "@/lib/types";

interface NRFPreferencesContextValue {
  theme: ThemePreference;
  defaultLightBackgroundUrl: string;
  setDefaultLightBackgroundUrl: (val: string) => void;
  defaultDarkBackgroundUrl: string;
  setDefaultDarkBackgroundUrl: (val: string) => void;
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

const firstLightExtensionImage = lightExtensionImages[0]!;
const firstDarkExtensionImage = darkExtensionImages[0]!;

export function NRFPreferencesProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  // Read theme from system/user settings via next-themes (no local override)
  const { resolvedTheme } = useTheme();

  // Map next-themes resolved theme to our ThemePreference enum
  // Default to DARK if theme hasn't resolved yet
  const theme: ThemePreference =
    resolvedTheme === "light" ? ThemePreference.LIGHT : ThemePreference.DARK;

  const [defaultLightBackgroundUrl, setDefaultLightBackgroundUrl] =
    useLocalStorageState<string>(
      LocalStorageKeys.LIGHT_BG_URL,
      firstLightExtensionImage
    );
  const [defaultDarkBackgroundUrl, setDefaultDarkBackgroundUrl] =
    useLocalStorageState<string>(
      LocalStorageKeys.DARK_BG_URL,
      firstDarkExtensionImage
    );
  const [useOnyxAsNewTab, setUseOnyxAsNewTab] = useLocalStorageState<boolean>(
    LocalStorageKeys.USE_ONYX_AS_NEW_TAB,
    true
  );

  useEffect(() => {
    if (theme === ThemePreference.DARK) {
      notifyExtensionOfThemeChange(theme, defaultDarkBackgroundUrl);
    } else {
      notifyExtensionOfThemeChange(theme, defaultLightBackgroundUrl);
    }
  }, [theme, defaultLightBackgroundUrl, defaultDarkBackgroundUrl]);

  return (
    <NRFPreferencesContext.Provider
      value={{
        theme,
        defaultLightBackgroundUrl,
        setDefaultLightBackgroundUrl,
        defaultDarkBackgroundUrl,
        setDefaultDarkBackgroundUrl,
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
