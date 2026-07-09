"use client";

import { useEffect, useRef } from "react";
import { useRouter, usePathname } from "next/navigation";
import type { Route } from "next";
import useSWR from "swr";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { SWR_KEYS } from "@/lib/swr-keys";
import { AuthType, AuthTypeMetadata } from "@/lib/auth/types";
import { User } from "@/lib/types";
import { getSecondsUntilExpiration } from "@opal/time";
import { logout } from "@/lib/users/svc";
import { useCurrentUser } from "@/lib/users/hooks";
import { getAuthRedirect, AuthPage } from "@/lib/auth/redirect";
import { usePHFeatureFlag, PHFeatureFlag } from "@/lib/analytics/hooks";
import { isAuthPath } from "@/lib/auth/paths";

interface AuthTypeAPIResponse {
  auth_type: string;
  requires_verification: boolean;
  anonymous_user_enabled: boolean | null;
  password_min_length: number;
  has_users: boolean;
  oauth_enabled: boolean;
}

const DEFAULT_AUTH_TYPE_METADATA: AuthTypeMetadata = {
  authType: NEXT_PUBLIC_CLOUD_ENABLED ? AuthType.CLOUD : AuthType.BASIC,
  autoRedirect: false,
  requiresVerification: false,
  anonymousUserEnabled: null,
  passwordMinLength: 0,
  hasUsers: false,
  oauthEnabled: false,
};

async function fetchAuthTypeMetadata(url: string): Promise<AuthTypeMetadata> {
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch auth type metadata");
  const data: AuthTypeAPIResponse = await res.json();
  const authType = NEXT_PUBLIC_CLOUD_ENABLED
    ? AuthType.CLOUD
    : (data.auth_type as AuthType);
  return {
    authType,
    autoRedirect: authType === AuthType.OIDC || authType === AuthType.SAML,
    requiresVerification: data.requires_verification,
    anonymousUserEnabled: data.anonymous_user_enabled,
    passwordMinLength: data.password_min_length,
    hasUsers: data.has_users,
    oauthEnabled: data.oauth_enabled,
  };
}

export function useAuthTypeMetadata(): {
  authTypeMetadata: AuthTypeMetadata;
  isLoading: boolean;
  error: Error | undefined;
} {
  const { data, error, isLoading } = useSWR<AuthTypeMetadata>(
    SWR_KEYS.authType,
    fetchAuthTypeMetadata,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      revalidateIfStale: false,
      dedupingInterval: 30_000,
    }
  );

  return {
    authTypeMetadata: data ?? DEFAULT_AUTH_TYPE_METADATA,
    isLoading,
    error,
  };
}

export function useAuthRedirect(currentPage: AuthPage): boolean {
  const { user, isLoading } = useCurrentUser();
  const { authTypeMetadata, isLoading: isAuthTypeLoading } =
    useAuthTypeMetadata();
  const signupDisabled = usePHFeatureFlag(PHFeatureFlag.SIGNUP_DISABLED);
  const router = useRouter();
  const isAuthStateLoading = isLoading || isAuthTypeLoading;

  useEffect(() => {
    if (isAuthStateLoading) return;
    const destination = getAuthRedirect(
      user,
      authTypeMetadata,
      currentPage,
      signupDisabled
    );
    if (destination) router.replace(destination as Route);
  }, [
    isAuthStateLoading,
    user,
    authTypeMetadata,
    currentPage,
    signupDisabled,
    router,
  ]);

  return isAuthStateLoading;
}

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
