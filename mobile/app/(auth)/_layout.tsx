import { Stack } from "expo-router";

// Unauthenticated flow group. The root redirect (driven by AuthProvider in
// doc 07) sends logged-out users here; URLs are unaffected by the group name.
export default function AuthLayout() {
  return <Stack screenOptions={{ headerShown: false }} />;
}
