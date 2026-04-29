"use client";

import { useEffect, useRef } from "react";
import { User } from "@/lib/types";
import { NO_AUTH_USER_ID } from "@/lib/extension/constants";
import { AuthTypeMetadata } from "@/hooks/useAuthTypeMetadata";
import { AuthType } from "@/lib/constants";

const REFRESH_INTERVAL = 600000;
const MIN_REFRESH_GAP_MS = REFRESH_INTERVAL - 60000;
const VISIBILITY_REFRESH_GAP_MS = 60000;

export function useTokenRefresh(
  user: User | null,
  authTypeMetadata: AuthTypeMetadata,
  authTypeMetadataLoading: boolean,
  onRefreshFail: () => Promise<void>
) {
  // Refs (not state) so updates do not retrigger the effect. lastAttemptRef
  // is bumped on every attempt — including failures — so that a 404 cannot
  // compound into a re-render loop with the gate permanently open.
  const lastAttemptRef = useRef<number>(Date.now());
  const isFirstLoadRef = useRef(true);

  useEffect(() => {
    // The SWR fallback for auth type defaults to BASIC; bail until the real
    // value loads, otherwise SAML/OIDC users will hit /api/auth/refresh
    // (which is not registered for those auth types) and 404.
    if (authTypeMetadataLoading) return;

    if (
      !user ||
      user.id === NO_AUTH_USER_ID ||
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

    refreshTokenPeriodically();

    const intervalId = setInterval(refreshTokenPeriodically, REFRESH_INTERVAL);

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
