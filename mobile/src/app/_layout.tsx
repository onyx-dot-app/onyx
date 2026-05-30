import { Stack } from "expo-router";

// Minimal root layout (foundation). The real navigation tree is owned by
// docs/plans/2026-05-30-mobile-app/04-app-framework-navigation.md.
export default function RootLayout() {
  return <Stack screenOptions={{ headerShown: false }} />;
}
