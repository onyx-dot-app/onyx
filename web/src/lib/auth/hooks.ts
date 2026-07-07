"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { type KeyedMutator } from "swr";
import { RedirectError } from "@/lib/fetcher";
import { User } from "@/lib/types";
import { getSecondsUntilExpiration } from "@opal/time";
import { NEXT_PUBLIC_CUSTOM_REFRESH_URL } from "@/lib/constants";
import { logout, refreshToken } from "@/lib/users/svc";

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function computeSecondsUntilExpiration(user: User): number | null {
  const expiries: Date[] = [];
  if (
    user.current_token_created_at &&
    user.current_token_expiry_length !== undefined
  ) {
    const createdAt = new Date(user.current_token_created_at);
    expiries.push(
      new Date(createdAt.getTime() + user.current_token_expiry_length * 1000)
    );
  }
  if (user.oidc_expiry) {
    expiries.push(new Date(user.oidc_expiry));
  }
  if (expiries.length === 0) return null;
  return Math.min(...expiries.map(getSecondsUntilExpiration));
}

// ---------------------------------------------------------------------------
// useTokenExpiry
// ---------------------------------------------------------------------------

/**
 * Tracks whether the current user's token has expired client-side.
 *
 * Arms a `setTimeout` based on the user's token fields and re-arms it
 * whenever the user object changes (e.g. after a successful refresh).
 * Returns a stable `setupExpirationTimeout` so `useCustomTokenRefresh` can
 * re-arm the timer after obtaining a new token.
 */
export function useTokenExpiry(user: User | null | undefined): {
  expired: boolean;
  setupExpirationTimeout: (secondsUntilExpiration: number) => void;
} {
  const [expired, setExpired] = useState(false);
  const expirationTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
    null
  );

  const setupExpirationTimeout = useCallback(
    (secondsUntilExpiration: number) => {
      if (expirationTimeoutRef.current) {
        clearTimeout(expirationTimeoutRef.current);
      }
      expirationTimeoutRef.current = setTimeout(
        () => {
          setExpired(true);
        },
        (secondsUntilExpiration + 10) * 1000
      );
    },
    []
  );

  useEffect(() => {
    if (!user) return;
    const seconds = computeSecondsUntilExpiration(user);
    if (seconds === null) return;
    setupExpirationTimeout(seconds);
  }, [user, setupExpirationTimeout]);

  useEffect(() => {
    return () => {
      if (expirationTimeoutRef.current) {
        clearTimeout(expirationTimeoutRef.current);
      }
    };
  }, []);

  return { expired, setupExpirationTimeout };
}

// ---------------------------------------------------------------------------
// useCustomTokenRefresh
// ---------------------------------------------------------------------------

/**
 * Handles enterprise token refresh via `NEXT_PUBLIC_CUSTOM_REFRESH_URL`.
 *
 * Sets up a 15-minute refresh interval and kicks off an immediate refresh if
 * the token expires before the next scheduled interval. Re-arms the expiry
 * timeout on success. No-ops when `NEXT_PUBLIC_CUSTOM_REFRESH_URL` is unset.
 */
export function useCustomTokenRefresh(
  user: User | null | undefined,
  setupExpirationTimeout: (secondsUntilExpiration: number) => void,
  mutateUser: KeyedMutator<User | null>
): void {
  const refreshIntervalRef = useRef<ReturnType<typeof setInterval> | null>(
    null
  );

  useEffect(() => {
    if (!user || !NEXT_PUBLIC_CUSTOM_REFRESH_URL) return;

    const seconds = computeSecondsUntilExpiration(user);
    if (seconds === null) return;

    const refreshUrl = NEXT_PUBLIC_CUSTOM_REFRESH_URL;

    const attemptTokenRefresh = async () => {
      let retryCount = 0;
      const maxRetries = 3;

      while (retryCount < maxRetries) {
        try {
          const refreshTokenData = await refreshToken(refreshUrl);
          if (!refreshTokenData) throw new Error("Failed to refresh token");

          const response = await fetch(
            "/api/enterprise-settings/refresh-token",
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(refreshTokenData),
            }
          );
          if (!response.ok)
            throw new Error(`HTTP error! status: ${response.status}`);

          // Wait for the backend to process the new token.
          await new Promise((resolve) => setTimeout(resolve, 4000));

          const updatedUser = await mutateUser();
          if (updatedUser) {
            const newSeconds = computeSecondsUntilExpiration(updatedUser);
            if (newSeconds !== null) {
              setupExpirationTimeout(newSeconds);
              console.debug(
                `Token refreshed, new expiration in ${newSeconds} seconds`
              );
            }
          }
          break;
        } catch (error) {
          console.error(
            `Error refreshing token (attempt ${retryCount + 1}/${maxRetries}):`,
            error
          );
          retryCount++;
          if (retryCount < maxRetries) {
            await new Promise((resolve) =>
              setTimeout(resolve, Math.pow(2, retryCount) * 1000)
            );
          } else {
            console.error("Max retry attempts reached");
          }
        }
      }
    };

    const REFRESH_INTERVAL_SECONDS = 60 * 15;

    if (refreshIntervalRef.current) clearInterval(refreshIntervalRef.current);
    refreshIntervalRef.current = setInterval(() => {
      if (document.hidden) return;
      attemptTokenRefresh();
    }, REFRESH_INTERVAL_SECONDS * 1000);

    if (seconds < REFRESH_INTERVAL_SECONDS) {
      attemptTokenRefresh();
    }

    return () => {
      if (refreshIntervalRef.current) {
        clearInterval(refreshIntervalRef.current);
      }
    };
  }, [user, setupExpirationTimeout, mutateUser]);
}

// ---------------------------------------------------------------------------
// useSessionWatcher
// ---------------------------------------------------------------------------

/**
 * Detects whether the user's session has ended mid-use.
 *
 * Latches `hasSeenAuthenticatedUser` so that a fresh unauthenticated page
 * load (where the user was never logged in) does not trigger the logged-out
 * UI. Only signals `sessionEnded` when the user was previously authenticated
 * and is not currently on an auth route.
 *
 * Side effect: calls `logout()` to clear the server session on a 403 for a
 * previously-authenticated user.
 */
export function useSessionWatcher({
  user,
  userError,
  healthError,
  expired,
}: {
  user: User | null | undefined;
  userError: (Error & { status?: number }) | undefined;
  healthError: unknown;
  expired: boolean;
}): { sessionEnded: boolean } {
  const hasSeenAuthenticatedUserRef = useRef(false);
  const pathname = usePathname();

  if (user) {
    hasSeenAuthenticatedUserRef.current = true;
  }

  const isAuthPage = pathname?.startsWith("/auth") ?? false;
  const sessionEnded =
    (userError?.status === 403 ||
      healthError instanceof RedirectError ||
      expired) &&
    hasSeenAuthenticatedUserRef.current &&
    !isAuthPage;

  useEffect(() => {
    if (userError?.status === 403 && hasSeenAuthenticatedUserRef.current) {
      logout();
    }
  }, [userError]);

  return { sessionEnded };
}
