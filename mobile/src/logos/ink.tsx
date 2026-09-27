// A few brand marks carry the page's ink so they stay legible on both themes. Web writes that as
// `fill="var(--text-05)"` or a `dark:fill-…` class, neither of which RN resolves inside an SVG.
import { useColorScheme } from "react-native";
import { varsDark, varsLight } from "@onyx-ai/shared/native";

export interface LogoInk {
  isDark: boolean;
  token: (name: string) => string;
}

export function useLogoInk(): LogoInk {
  const isDark = useColorScheme() === "dark";
  const vars = isDark ? varsDark : varsLight;
  return {
    isDark,
    token: (name: string) => vars[name] ?? "#000000",
  };
}
