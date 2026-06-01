import React, { createContext, useContext, useMemo } from "react";
import { View } from "react-native";
import { vars, useColorScheme } from "nativewind";

import { lightColors, darkColors } from "@/theme/generated/colors";
import type { ColorToken } from "@/theme/generated/colors";

// Light and dark share the same key set (guaranteed by the generator), so this
// is keyed by ColorToken regardless of scheme.
type ColorMap = Record<ColorToken, string>;

const ThemeColorsContext = createContext<ColorMap>(lightColors);

interface ThemeProviderProps {
  children: React.ReactNode;
}

// Exposes every token as a `--<token>` var. The generated NativeWind preset maps
// each Tailwind color to `var(--<token>)`, so setting these on a wrapping View
// makes classes like `bg-background-neutral-00` resolve for all descendants.
function buildThemeVars(colors: ColorMap): Record<string, string> {
  const entries: Record<string, string> = {};
  for (const [token, value] of Object.entries(colors)) {
    entries[`--${token}`] = value;
  }
  return entries;
}

export function ThemeProvider({ children }: ThemeProviderProps) {
  // Respects system when set to "system"; undefined falls back to light.
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

// Resolved hex values, for use outside className styling (status bar, charts).
export function useThemeColors(): ColorMap {
  return useContext(ThemeColorsContext);
}

export function useToken(name: ColorToken): string {
  return useContext(ThemeColorsContext)[name];
}
