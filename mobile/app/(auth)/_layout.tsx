import { Redirect, Stack } from "expo-router";

import { useAuth } from "@/auth";

// app/index.tsx unmounts after redirecting, so this layout must ALSO guard:
// when status flips to signedIn (e.g. login here) it reactively bounces into the
// app. Without it, login succeeds but the UI stays on the login screen.
export default function AuthLayout() {
  const { status } = useAuth();

  if (status === "loading") return null;

  if (status === "signedIn") {
    // typedRoutes is on but .expo/types isn't generated offline, so cast the Href.
    return <Redirect href={"/(app)/(chat)" as never} />;
  }

  return <Stack screenOptions={{ headerShown: false }} />;
}
