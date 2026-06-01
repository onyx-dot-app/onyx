import React, { createContext, useContext, useMemo } from "react";
import { View } from "react-native";
import { vars, useColorScheme } from "nativewind";

import { lightColors, darkColors } from "@/theme/generated/colors";
import type { ColorToken } from "@/theme/generated/colors";

// The resolved color map for the currently-active scheme. Both light and dark
// share the same key set (guaranteed by the generator), so this is keyed by
// ColorToken regardless of scheme.
type ColorMap = Record<ColorToken, string>;

const ThemeColorsContext = createContext<ColorMap>(lightColors);

interface ThemeProviderProps {
  children: React.ReactNode;
}

/**
 * Builds the NativeWind `vars()` style for a color map by exposing every token
 * as a `--<token>` CSS variable. The generated NativeWind preset maps each
 * Tailwind color to `var(--<token>)`, so setting these vars on a wrapping View
 * makes classes like `bg-background-neutral-00` resolve for all descendants.
 */
function buildThemeVars(colors: ColorMap): Record<string, string> {
  const entries: Record<string, string> = {};
  for (const [token, value] of Object.entries(colors)) {
    entries[`--${token}`] = value;
  }
  return entries;
}

/**
 * Applies the Opal theme to the whole subtree. Resolves light/dark/system via
 * the device color scheme and injects the matching token values as CSS vars
 * through NativeWind's `vars()`. Wrap the app once near the root.
 */
export function ThemeProvider({ children }: ThemeProviderProps) {
  // `colorScheme` reflects the active scheme (respecting system when set to
  // "system"); undefined falls back to light.
  const { colorScheme } = useColorScheme();
  const isDark = colorScheme === "dark";

  const colors: ColorMap = isDark ? darkColors : lightColors;

  const style = useMemo(() => vars(buildThemeVars(colors)), [colors]);

  return (
    <ThemeColorsContext.Provider value={colors}>
      <View style={style} className="flex-1">
        {children}
      </View>
    </ThemeColorsContext.Provider>
  );
}

/**
 * Returns the active resolved color map (concrete hex values). Handy where raw
 * values are needed outside of className styling, e.g. the status bar or charts.
 */
export function useThemeColors(): ColorMap {
  return useContext(ThemeColorsContext);
}

/**
 * Returns a single resolved color value for the active scheme.
 */
export function useToken(name: ColorToken): string {
  return useContext(ThemeColorsContext)[name];
}
