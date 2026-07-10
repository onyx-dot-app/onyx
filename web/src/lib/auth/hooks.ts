"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import useSWR from "swr";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { SWR_KEYS } from "@/lib/swr-keys";
import { NO_AUTH_USER_ID } from "@/lib/extension/constants";
import { AuthType, AuthTypeMetadata } from "@/lib/auth/types";
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

// ---------------------------------------------------------------------------
// useAuthTypeMetadata
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// useTokenRefresh
// ---------------------------------------------------------------------------

const REFRESH_INTERVAL = 600000;
const MIN_REFRESH_GAP_MS = REFRESH_INTERVAL - 60000;
const VISIBILITY_REFRESH_GAP_MS = 60000;

export function useTokenRefresh(
  user: User | null,
  authTypeMetadata: AuthTypeMetadata,
  authTypeMetadataLoading: boolean,
  onRefreshFail: () => Promise<void>
) {
  const lastAttemptRef = useRef<number>(Date.now());
  const isFirstLoadRef = useRef(true);

  useEffect(() => {
    if (authTypeMetadataLoading) return;

    if (
      !user ||
      user.id === NO_AUTH_USER_ID ||
      user.is_anonymous_user ||
      authTypeMetadata.authType === AuthType.OIDC ||
      authTypeMetadata.authType === AuthType.SAML
    ) {
      return;
    }

    const refreshTokenPeriodically = async () => {
      const isTimeToRefresh =
        isFirstLoadRef.current ||
        Date.now() - lastAttemptRef.current > MIN_REFRESH_GAP_MS;

      if (!isTimeToRefresh) return;

      isFirstLoadRef.current = false;
      lastAttemptRef.current = Date.now();

      try {
        const response = await fetch("/api/auth/refresh", {
          method: "POST",
          credentials: "include",
        });

        if (response.ok) {
          console.debug("Auth token refreshed successfully");
        } else {
          console.warn("Failed to refresh auth token:", response.status);
          await onRefreshFail();
        }
      } catch (error) {
        console.error("Error refreshing auth token:", error);
      }
    };

    if (!document.hidden) {
      refreshTokenPeriodically();
    }

    const intervalId = setInterval(() => {
      if (document.hidden) return;
      refreshTokenPeriodically();
    }, REFRESH_INTERVAL);

    const handleVisibilityChange = () => {
      if (
        document.visibilityState === "visible" &&
        Date.now() - lastAttemptRef.current > VISIBILITY_REFRESH_GAP_MS
      ) {
        refreshTokenPeriodically();
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      clearInterval(intervalId);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [user, authTypeMetadata, authTypeMetadataLoading, onRefreshFail]);
}
