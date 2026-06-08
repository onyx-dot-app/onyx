import { Stack } from "expo-router";

// Shared route-group layout: a header-less Stack with no extra options or logic.
// Route groups whose _layout only needs to push native screens (no modal
// presentation, no auth guard, no wrappers) default-export this directly.
export function HiddenHeaderStack() {
  return <Stack screenOptions={{ headerShown: false }} />;
}
