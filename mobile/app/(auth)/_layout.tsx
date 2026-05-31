import { Redirect, Stack } from "expo-router";

import { useAuth } from "@/auth";

// Unauthenticated flow group. The root redirect (app/index.tsx) sends logged-out
// users here, but that route unmounts once it redirects — so we ALSO guard here.
// When auth status flips to "signedIn" (e.g. right after a successful login on a
// screen in this group), this layout re-renders and reactively bounces into the
// app. Without this, login succeeds silently but the UI stays on the login screen.
export default function AuthLayout() {
  const { status } = useAuth();

  // Still resolving the token on cold start — let the splash/index handle it.
  if (status === "loading") return null;

  // Already authenticated — don't show auth screens.
  if (status === "signedIn") {
    // typedRoutes is on but .expo/types isn't generated offline, so cast the Href.
    return <Redirect href={"/(app)/(chat)" as never} />;
  }

  return <Stack screenOptions={{ headerShown: false }} />;
}
