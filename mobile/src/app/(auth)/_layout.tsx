// Layout for the unauthenticated route group: the connect (instance URL) and login
// screens. Headerless, like the root stack; the AuthGate (root layout) decides when
// these screens are reachable.
import { Stack } from "expo-router";

export default function AuthLayout() {
  return <Stack screenOptions={{ headerShown: false }} />;
}
