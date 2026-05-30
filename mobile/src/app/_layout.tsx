import "../../global.css";

import { Stack } from "expo-router";

import { ThemeProvider } from "@/theme/ThemeProvider";

// Minimal root layout (foundation). The real navigation tree is owned by
// docs/plans/2026-05-30-mobile-app/04-app-framework-navigation.md.
export default function RootLayout() {
  return (
    <ThemeProvider>
      <Stack screenOptions={{ headerShown: false }} />
    </ThemeProvider>
  );
}
