// AuthGate — wraps the root navigator and steers between the app and the auth screens
// (decision in `resolveAuthGate`, pure + unit-tested).
//
// Navigation is imperative (`router.replace`), not `<Redirect>`: at the root layout
// <Redirect>'s `useFocusEffect` has no focused route to bind to. `children` (the <Stack>)
// renders in every branch so the navigator stays mounted; the splash overlays it.
import { router, useSegments } from "expo-router";
import * as React from "react";
import { ActivityIndicator, View } from "react-native";

import { isAuthError } from "@/api/errors";
import { resolveAuthGate } from "@/components/auth/authRoute";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { useSession } from "@/state/session";

function AuthSplash() {
  return (
    <View
      accessibilityViewIsModal
      className="absolute inset-0 items-center justify-center bg-background-neutral-00"
    >
      <ActivityIndicator accessibilityLabel="Loading" />
    </View>
  );
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  const serverUrl = useSession((state) => state.serverUrl);
  const segments = useSegments();
  const { data, error } = useCurrentUser();

  const resolution = resolveAuthGate({
    serverUrl,
    isAuthed: data !== undefined,
    isAuthError: isAuthError(error),
    segments,
  });

  const redirectTo = resolution.kind === "redirect" ? resolution.to : null;
  React.useEffect(() => {
    if (redirectTo) router.replace(redirectTo);
  }, [redirectTo]);

  // Mask the navigator while identity resolves and during the frame before a redirect.
  const showSplash = resolution.kind !== "render";

  return (
    <>
      {children}
      {showSplash ? <AuthSplash /> : null}
    </>
  );
}
