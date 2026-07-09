"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import { User } from "@/lib/types";
import { getSecondsUntilExpiration } from "@opal/time";
import { logout } from "@/lib/users/svc";
import { useCurrentUser } from "@/lib/users/hooks";
import { isAuthPath } from "@/lib/auth/paths";

function computeSecondsUntilExpiration(user: User): number | null {
  if (!user.token_expires_at) return null;
  return getSecondsUntilExpiration(new Date(user.token_expires_at));
}

/**
 * Detects whether the user's session has ended mid-use.
 *
 * Schedules a `mutateUser()` call at `token_expires_at` so the server's 403
 * response is the single mechanism for both timer-based and unexpected
 * revocation. The backend transparently refreshes near-expiry OAuth tokens on
 * every request via `_maybe_refresh_oauth_tokens`, so a successful `/api/me`
 * response returns a fresh `token_expires_at` and re-arms the timer.
 *
 * Suppressed on auth routes. Entering `/auth` also resets the
 * hasSeenAuthenticatedUser latch so a lingering 403 can't resurface the
 * "logged out" modal on the login page.
 *
 * Side effect: calls `logout()` to clear the server session on a 403 for a
 * previously-authenticated user.
 */
export function useSessionWatcher(): boolean {
  const pathname = usePathname();
  const inAuthFlow = isAuthPath(pathname);

  const { user, mutateUser, userError } = useCurrentUser();
  const expiryTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hasSeenAuthenticatedUserRef = useRef(false);

  // Entering login/logout is a session boundary: forget the prior session so a
  // lingering 403 can't resurface the "logged out" modal on the login page.
  if (inAuthFlow) {
    hasSeenAuthenticatedUserRef.current = false;
  } else if (user) {
    hasSeenAuthenticatedUserRef.current = true;
  }

  useEffect(() => {
    if (inAuthFlow || !user) return;
    const seconds = computeSecondsUntilExpiration(user);
    if (seconds === null) return;
    if (expiryTimeoutRef.current) clearTimeout(expiryTimeoutRef.current);
    expiryTimeoutRef.current = setTimeout(() => mutateUser(), seconds * 1000);
  }, [inAuthFlow, user, mutateUser]);

  useEffect(() => {
    return () => {
      if (expiryTimeoutRef.current) clearTimeout(expiryTimeoutRef.current);
    };
  }, []);

  useEffect(() => {
    if (inAuthFlow) return;
    if (userError?.status === 403 && hasSeenAuthenticatedUserRef.current) {
      logout();
    }
  }, [inAuthFlow, userError]);

  return (
    !inAuthFlow &&
    userError?.status === 403 &&
    hasSeenAuthenticatedUserRef.current
  );
}
