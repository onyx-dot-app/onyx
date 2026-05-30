import { Redirect } from "expo-router";

import { useAuth } from "@/auth";

// Entry route = the auth gate. AuthProvider resolves the JWT (from a cold-start
// OAuth deep link or SecureStore) and we redirect accordingly.
export default function Index() {
  const { status } = useAuth();

  // Still resolving — the native splash is up; render nothing.
  if (status === "loading") return null;

  // typedRoutes is on but .expo/types isn't generated offline, so cast the Href.
  return (
    <Redirect
      href={(status === "signedIn" ? "/(app)/(chat)" : "/(auth)/login") as never}
    />
  );
}
