import { Stack } from "expo-router";

// Settings tab owns a Stack so appearance (and future sub-screens) push over
// the settings index.
export default function SettingsLayout() {
  return <Stack screenOptions={{ headerShown: false }} />;
}
