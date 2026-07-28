// Imperative nav, not `<Redirect>`: at the root layout <Redirect>'s `useFocusEffect` has no
// focused route to bind to. `children` renders in every branch so the navigator stays mounted.
import { router, useSegments } from "expo-router";
import * as React from "react";
import { ActivityIndicator, View } from "react-native";

import { isAuthError } from "@/api/errors";
import { AuthUnreachable } from "@/components/auth/AuthUnreachable";
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
  const status = useSession((state) => state.status);
  const segments = useSegments();
  const { data, error, isError, isFetching, refetch } = useCurrentUser();
  const authError = isAuthError(error);

  const resolution = resolveAuthGate({
    serverUrl,
    status,
    isAuthed: data !== undefined,
    isAuthError: authError,
    // `isAuthed` wins, so a background refetch failing over cached identity keeps the app up.
    isUnreachable: isError && !authError,
    segments,
  });

  const redirectTo = resolution.kind === "redirect" ? resolution.to : null;
  React.useEffect(() => {
    if (redirectTo) router.replace(redirectTo);
  }, [redirectTo]);

  // Overlay: actionable error on a settled failure, else the splash while identity resolves.
  const overlay =
    resolution.kind === "error" ? (
      <AuthUnreachable onRetry={() => refetch()} retrying={isFetching} />
    ) : resolution.kind !== "render" ? (
      <AuthSplash />
    ) : null;

  return (
    <>
      {children}
      {overlay}
    </>
  );
}
