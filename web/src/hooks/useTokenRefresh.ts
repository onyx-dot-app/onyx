import { useState, useEffect, useRef } from "react";
import { User } from "@/lib/types";
import { NO_AUTH_USER_ID } from "@/lib/extension/constants";
import { AuthTypeMetadata } from "@/lib/userSS";

// Refresh token every 10 minutes (600000ms)
// This is shorter than the session expiry time to ensure tokens stay valid
const REFRESH_INTERVAL = 600000;

//  Custom hook for handling JWT token refresh for current user
export function useTokenRefresh(
  user: User | null,
  authTypeMetadata: AuthTypeMetadata,
  onRefreshFail: () => Promise<void>
) {
  // Track last refresh time to avoid unnecessary calls
  const [lastTokenRefresh, setLastTokenRefresh] = useState<number>(Date.now());

  // Use a ref to track first load
  const isFirstLoad = useRef(true);

  useEffect(() => {
    if (
      !user ||
      user.id === NO_AUTH_USER_ID ||
      authTypeMetadata.authType === "oidc" ||
      authTypeMetadata.authType === "saml"
    )
      return;

    const refreshTokenPeriodically = async () => {
      try {
        // Skip time check if this is first load - we always refresh on first load
        const isTimeToRefresh =
          isFirstLoad.current ||
          Date.now() - lastTokenRefresh > REFRESH_INTERVAL - 60000;

        if (!isTimeToRefresh) {
          return;
        }

        // Reset first load flag
        if (isFirstLoad.current) {
          isFirstLoad.current = false;
        }

        const response = await fetch("/api/auth/refresh", {
          method: "POST",
          credentials: "include",
        });

        if (response.ok) {
          // Update last refresh time on success
          setLastTokenRefresh(Date.now());
          console.debug("Auth token refreshed successfully");
        } else {
          console.warn("Failed to refresh auth token:", response.status);
          // If token refresh fails, try to get current user info
          await onRefreshFail();
        }
      } catch (error) {
        console.error("Error refreshing auth token:", error);
      }
    };

    // Always attempt to refresh on first component mount
    // This helps ensure tokens are fresh, especially after browser refresh
    refreshTokenPeriodically();

    // Set up interval for periodic refreshes
    const intervalId = setInterval(refreshTokenPeriodically, REFRESH_INTERVAL);

    // Also refresh token on window focus, but no more than once per minute
    const handleVisibilityChange = () => {
      if (
        document.visibilityState === "visible" &&
        Date.now() - lastTokenRefresh > 60000
      ) {
        refreshTokenPeriodically();
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      clearInterval(intervalId);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [user, lastTokenRefresh, onRefreshFail]);

  return { lastTokenRefresh };
}
