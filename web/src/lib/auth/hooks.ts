"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import { type KeyedMutator } from "swr";
import { User } from "@/lib/types";
import { getSecondsUntilExpiration } from "@opal/time";
import { NEXT_PUBLIC_CUSTOM_REFRESH_URL } from "@/lib/constants";
import { logout, refreshToken } from "@/lib/users/svc";

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function computeSecondsUntilExpiration(user: User): number | null {
  if (!user.token_expires_at) return null;
  return getSecondsUntilExpiration(new Date(user.token_expires_at));
}

// ---------------------------------------------------------------------------
// useCustomTokenRefresh
// ---------------------------------------------------------------------------

/**
 * Handles enterprise token refresh via `NEXT_PUBLIC_CUSTOM_REFRESH_URL`.
 *
 * Sets up a 15-minute refresh interval and kicks off an immediate refresh if
 * the token expires before the next scheduled interval. After a successful
 * refresh, `mutateUser()` updates `user.token_expires_at`, which causes
 * `useSessionWatcher` to re-arm its expiry timer automatically. No-ops when
 * `NEXT_PUBLIC_CUSTOM_REFRESH_URL` is unset.
 */
export function useCustomTokenRefresh(
  user: User | null | undefined,
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

          await mutateUser();
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
  }, [user, mutateUser]);
}

// ---------------------------------------------------------------------------
// useSessionWatcher
// ---------------------------------------------------------------------------

/**
 * Detects whether the user's session has ended mid-use.
 *
 * Schedules a `mutateUser()` call at `token_expires_at` so the server's 403
 * response is the single mechanism for both timer-based and unexpected
 * revocation. Latches `hasSeenAuthenticatedUser` so a fresh unauthenticated
 * page load never triggers the logged-out UI. Suppressed on auth routes.
 *
 * Side effect: calls `logout()` to clear the server session on a 403 for a
 * previously-authenticated user.
 */
export function useSessionWatcher({
  user,
  userError,
  mutateUser,
}: {
  user: User | null | undefined;
  userError: (Error & { status?: number }) | undefined;
  mutateUser: KeyedMutator<User | null>;
}): { sessionEnded: boolean } {
  const expiryTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hasSeenAuthenticatedUserRef = useRef(false);
  const pathname = usePathname();

  if (user) {
    hasSeenAuthenticatedUserRef.current = true;
  }

  useEffect(() => {
    if (!user) return;
    const seconds = computeSecondsUntilExpiration(user);
    if (seconds === null) return;
    if (expiryTimeoutRef.current) {
      clearTimeout(expiryTimeoutRef.current);
    }
    expiryTimeoutRef.current = setTimeout(() => mutateUser(), seconds * 1000);
  }, [user, mutateUser]);

  useEffect(() => {
    return () => {
      if (expiryTimeoutRef.current) {
        clearTimeout(expiryTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (userError?.status === 403 && hasSeenAuthenticatedUserRef.current) {
      logout();
    }
  }, [userError]);

  const isAuthPage = pathname?.startsWith("/auth") ?? false;
  const sessionEnded =
    userError?.status === 403 &&
    hasSeenAuthenticatedUserRef.current &&
    !isAuthPage;

  return { sessionEnded };
}
