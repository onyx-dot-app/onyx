"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { NO_AUTH_USER_ID } from "@/lib/extension/constants";
import { AuthTypeMetadata, SessionEndReason } from "@/lib/auth/types";
import { FetchError } from "@/lib/fetcher";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { User } from "@/lib/types";
import { getSecondsUntilExpiration } from "@opal/time";
import { logout } from "@/lib/users/svc";
import { useCurrentUser } from "@/lib/users/hooks";
import { isAuthPath } from "@/lib/auth/paths";
import { fetchAuthTypeMetadata } from "@/lib/auth/svc";

const REFRESH_INTERVAL = 600000;
const MIN_REFRESH_GAP_MS = REFRESH_INTERVAL - 60000;
const VISIBILITY_REFRESH_GAP_MS = 60000;

export function useAuthTypeMetadata(): {
  authTypeMetadata: AuthTypeMetadata | undefined;
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

  return { authTypeMetadata: data, isLoading, error };
}

function computeSecondsUntilExpiration(user: User): number | null {
  if (!user.token_expires_at) return null;
  return getSecondsUntilExpiration(new Date(user.token_expires_at));
}

function parseSessionEndReason(error: unknown): SessionEndReason | null {
  if (!(error instanceof FetchError)) return null;
  const errorCode: unknown = error.info?.error_code;
  return (Object.values(SessionEndReason) as unknown[]).includes(errorCode)
    ? (errorCode as SessionEndReason)
    : null;
}

export interface SessionWatcherResult {
  sessionEnded: boolean;
  /** Rejection code from the 403 that ended the session; null when absent. */
  sessionEndReason: SessionEndReason | null;
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
export function useSessionWatcher(): SessionWatcherResult {
  const pathname = usePathname();
  const inAuthFlow = isAuthPath(pathname);

  const { user, mutateUser, userError } = useCurrentUser();
  const expiryTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hasSeenAuthenticatedUserRef = useRef(false);
  const sessionEndReasonRef = useRef<SessionEndReason | null>(null);

  // Entering login/logout is a session boundary: forget the prior session so a
  // lingering 403 can't resurface the "logged out" modal on the login page.
  if (inAuthFlow) {
    hasSeenAuthenticatedUserRef.current = false;
  } else if (user) {
    hasSeenAuthenticatedUserRef.current = true;
  }

  const sessionEnded =
    !inAuthFlow &&
    userError?.status === 403 &&
    hasSeenAuthenticatedUserRef.current;

  // Latch the first 403's reason: a later refetch can reclassify (e.g. EXPIRED
  // becomes UNRECOGNIZED once the server-side grace window lapses) and must
  // not flip the modal copy while it is up.
  if (!sessionEnded) {
    sessionEndReasonRef.current = null;
  } else if (sessionEndReasonRef.current === null) {
    sessionEndReasonRef.current = parseSessionEndReason(userError);
  }

  useEffect(() => {
    if (inAuthFlow || !user) return;
    const seconds = computeSecondsUntilExpiration(user);
    if (seconds === null) return;
    if (expiryTimeoutRef.current) clearTimeout(expiryTimeoutRef.current);
    // Fire 2s past the wall: firing at (or, via flooring, just before) it gets
    // a 200 with deep-equal data, which never re-runs this effect — the
    // one-shot timer disarms and the session dies unwatched. A 200 after the
    // wall means the session moved, and its new expiry re-arms us.
    expiryTimeoutRef.current = setTimeout(
      () => mutateUser(),
      (seconds + 2) * 1000
    );
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

  return { sessionEnded, sessionEndReason: sessionEndReasonRef.current };
}

export function useIsMultiTenant(): boolean | null {
  // Delegate to useAuthTypeMetadata so the shared SWR key always holds the
  // camelCase-mapped shape — a raw fetcher here would poison the cache for
  // every other consumer of the key.
  const { authTypeMetadata, isLoading, error } = useAuthTypeMetadata();

  if (NEXT_PUBLIC_CLOUD_ENABLED) {
    return true;
  }

  if (error || isLoading) {
    return null;
  }

  return authTypeMetadata?.multiTenant ?? null;
}

// Pass-through forwards the logged-in user's OAuth access token, so offer it
// only when users authenticate with an OAuth-capable method (Google/OIDC).
// SAML grants no OAuth token, so a SAML-only deployment must not enable it.
export function useOAuthPassThroughEnabled(): boolean {
  const { authTypeMetadata } = useAuthTypeMetadata();
  return (
    authTypeMetadata?.oauthEnabled === true ||
    (authTypeMetadata?.ssoProviders ?? []).some(
      (p) => p.providerType === "OIDC" || p.providerType === "GOOGLE_OAUTH"
    )
  );
}

export function useTokenRefresh(
  user: User | null,
  authTypeMetadataLoading: boolean,
  onRefreshFail: () => Promise<void>
) {
  const lastAttemptRef = useRef<number>(Date.now());
  const isFirstLoadRef = useRef(true);

  useEffect(() => {
    // Wait only for the initial metadata load. On persistent error we still
    // refresh so a transient /auth/type failure cannot silently kill sessions.
    if (authTypeMetadataLoading) return;

    if (!user || user.id === NO_AUTH_USER_ID || user.is_anonymous_user) {
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
  }, [user, authTypeMetadataLoading, onRefreshFail]);
}
