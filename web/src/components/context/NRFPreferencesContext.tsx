"use client";

import React, { createContext, useContext, useState, useEffect } from "react";
import { Shortcut } from "@/app/chat/nrf/interfaces";
import { notifyExtensionOfThemeChange } from "@/lib/extension/utils";
import {
  darkExtensionImages,
  lightExtensionImages,
  LocalStorageKeys,
} from "@/lib/extension/constants";

interface NRFPreferencesContextValue {
  theme: string;
  setTheme: (t: string) => void;
  defaultLightBackgroundUrl: string;
  setDefaultLightBackgroundUrl: (val: string) => void;
  defaultDarkBackgroundUrl: string;
  setDefaultDarkBackgroundUrl: (val: string) => void;
  shortcuts: Shortcut[];
  setShortcuts: (s: Shortcut[]) => void;
  useOnyxAsNewTab: boolean;
  setUseOnyxAsNewTab: (v: boolean) => void;
  showShortcuts: boolean;
  setShowShortcuts: (v: boolean) => void;
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
    return undefined;
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
  const [theme, setTheme] = useLocalStorageState<string>(
    LocalStorageKeys.THEME,
    "dark"
  );
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
  const [shortcuts, setShortcuts] = useLocalStorageState<Shortcut[]>(
    LocalStorageKeys.SHORTCUTS,
    []
  );
  const [showShortcuts, setShowShortcuts] = useLocalStorageState<boolean>(
    LocalStorageKeys.SHOW_SHORTCUTS,
    false
  );
  const [useOnyxAsNewTab, setUseOnyxAsNewTab] = useLocalStorageState<boolean>(
    LocalStorageKeys.USE_ONYX_AS_NEW_TAB,
    true
  );

  useEffect(() => {
    if (theme === "dark") {
      notifyExtensionOfThemeChange(theme, defaultDarkBackgroundUrl);
    } else {
      notifyExtensionOfThemeChange(theme, defaultLightBackgroundUrl);
    }
  }, [theme, defaultLightBackgroundUrl, defaultDarkBackgroundUrl]);

  return (
    <NRFPreferencesContext.Provider
      value={{
        theme,
        setTheme,
        defaultLightBackgroundUrl,
        setDefaultLightBackgroundUrl,
        defaultDarkBackgroundUrl,
        setDefaultDarkBackgroundUrl,
        shortcuts,
        setShortcuts,
        useOnyxAsNewTab,
        setUseOnyxAsNewTab,
        showShortcuts,
        setShowShortcuts,
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
