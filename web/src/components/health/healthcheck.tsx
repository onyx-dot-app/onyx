"use client";

import { errorHandlingFetcher, RedirectError } from "@/lib/fetcher";
import useSWR from "swr";
import { Modal } from "../Modal";
import { useCallback, useEffect, useState, useRef } from "react";
import { getSecondsUntilExpiration } from "@/lib/time";
import { User } from "@/lib/types";
import { refreshToken } from "./refreshUtils";
import { NEXT_PUBLIC_CUSTOM_REFRESH_URL } from "@/lib/constants";
import { Button } from "../ui/button";
import { logout } from "@/lib/user";
import { usePathname, useRouter } from "next/navigation";
import { useAuthType } from "@/lib/hooks";
export const HealthCheckBanner = () => {
  const router = useRouter();
  const { error: healthError } = useSWR("/api/health", errorHandlingFetcher);
  const [expired, setExpired] = useState(false);
  const [showLoggedOutModal, setShowLoggedOutModal] = useState(false);
  const pathname = usePathname();
  const expirationTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const refreshIntervalRef = useRef<NodeJS.Timer | null>(null);
  const authType = useAuthType();
  const authTypeRef = useRef(authType);
  const hasHandledSessionRef = useRef(false);

  useEffect(() => {
    authTypeRef.current = authType;
  }, [authType]);

  // Reduce revalidation frequency with dedicated SWR config
  const {
    data: user,
    mutate: mutateUser,
    error: userError,
  } = useSWR<User>("/api/me", errorHandlingFetcher, {
    revalidateOnFocus: false,
    revalidateOnReconnect: false,
    dedupingInterval: 30000, // 30 seconds
  });

  // Function to handle the "Log in" button click
  const handleLogin = () => {
    setShowLoggedOutModal(false);
    router.push("/auth/login");
  };

  // Function to set up expiration timeout
  const setupExpirationTimeout = useCallback(
    (secondsUntilExpiration: number) => {
      // Clear any existing timeout
      if (expirationTimeoutRef.current) {
        clearTimeout(expirationTimeoutRef.current);
      }

      // Set timeout to show logout modal when session expires
      const timeUntilExpire = (secondsUntilExpiration + 10) * 1000;
      expirationTimeoutRef.current = setTimeout(() => {
        setExpired(true);
      }, timeUntilExpire);
    },
    []
  );

  // Clean up any timeouts/intervals when component unmounts
  useEffect(() => {
    return () => {
      if (expirationTimeoutRef.current) {
        clearTimeout(expirationTimeoutRef.current);
      }

      if (refreshIntervalRef.current) {
        clearInterval(refreshIntervalRef.current);
      }
    };
  }, []);

  // Set up token refresh logic if custom refresh URL exists
  useEffect(() => {
    if (!user) return;

    const secondsUntilExpiration = getSecondsUntilExpiration(user);
    if (secondsUntilExpiration === null) return;

    // Set up expiration timeout based on current user data
    setupExpirationTimeout(secondsUntilExpiration);

    if (NEXT_PUBLIC_CUSTOM_REFRESH_URL) {
      const refreshUrl = NEXT_PUBLIC_CUSTOM_REFRESH_URL;

      const attemptTokenRefresh = async () => {
        let retryCount = 0;
        const maxRetries = 3;

        while (retryCount < maxRetries) {
          try {
            const refreshTokenData = await refreshToken(refreshUrl);
            if (!refreshTokenData) {
              throw new Error("Failed to refresh token");
            }

            const response = await fetch(
              "/api/enterprise-settings/refresh-token",
              {
                method: "POST",
                headers: {
                  "Content-Type": "application/json",
                },
                body: JSON.stringify(refreshTokenData),
              }
            );
            if (!response.ok) {
              throw new Error(`HTTP error! status: ${response.status}`);
            }

            // Wait for backend to process the token
            await new Promise((resolve) => setTimeout(resolve, 4000));

            // Get updated user data
            const updatedUser = await mutateUser();

            if (updatedUser) {
              // Reset expiration timeout with new expiration time
              const newSecondsUntilExpiration =
                getSecondsUntilExpiration(updatedUser);
              if (newSecondsUntilExpiration !== null) {
                setupExpirationTimeout(newSecondsUntilExpiration);
                console.debug(
                  `Token refreshed, new expiration in ${newSecondsUntilExpiration} seconds`
                );
              }
            }

            break; // Success - exit the retry loop
          } catch (error) {
            console.error(
              `Error refreshing token (attempt ${
                retryCount + 1
              }/${maxRetries}):`,
              error
            );
            retryCount++;

            if (retryCount === maxRetries) {
              console.error("Max retry attempts reached");
            } else {
              // Wait before retrying (exponential backoff)
              await new Promise((resolve) =>
                setTimeout(resolve, Math.pow(2, retryCount) * 1000)
              );
            }
          }
        }
      };

      // Set up refresh interval
      const refreshInterval = 60 * 15; // 15 mins

      // Clear any existing interval
      if (refreshIntervalRef.current) {
        clearInterval(refreshIntervalRef.current);
      }

      refreshIntervalRef.current = setInterval(
        attemptTokenRefresh,
        refreshInterval * 1000
      );

      // If we're going to expire before the next refresh, kick off a refresh now
      if (secondsUntilExpiration < refreshInterval) {
        attemptTokenRefresh();
      }
    }
  }, [user, setupExpirationTimeout, mutateUser]);

  const redirectToLogin = useCallback(() => {
    const basePath = "/auth/login";

    if (typeof window === "undefined") {
      router.replace(
        `${basePath}?disableAutoRedirect=true&sessionExpired=true`
      );
      return;
    }

    const loginUrl = new URL(basePath, window.location.origin);
    loginUrl.searchParams.set("disableAutoRedirect", "true");
    loginUrl.searchParams.set("sessionExpired", "true");

    const nextPath =
      window.location.pathname + window.location.search + window.location.hash;
    if (nextPath) {
      loginUrl.searchParams.set("next", nextPath);
    }

    router.replace(`${loginUrl.pathname}${loginUrl.search}`);
  }, [router]);

  useEffect(() => {
    const forbidden =
      (userError && userError.status === 403) ||
      healthError instanceof RedirectError;
    const shouldHandle = !pathname?.includes("/auth") && (forbidden || expired);

    if (!shouldHandle || hasHandledSessionRef.current) {
      return;
    }

    hasHandledSessionRef.current = true;

    const finalize = () => {
      if (authTypeRef.current === "saml") {
        redirectToLogin();
      } else {
        setShowLoggedOutModal(true);
      }
    };

    if (forbidden) {
      logout()
        .catch((error) => {
          console.error("Error logging out after session issue:", error);
        })
        .finally(finalize);
    } else {
      finalize();
    }
  }, [userError, healthError, expired, pathname, redirectToLogin]);

  // Logged out modal
  if (showLoggedOutModal) {
    return (
      <Modal
        width="w-1/3"
        className="overflow-y-hidden flex flex-col"
        title="You Have Been Logged Out"
      >
        <div className="flex flex-col gap-y-4">
          <p className="text-sm">
            Your session has expired. Please log in again to continue.
          </p>
          <div className="flex flex-row gap-x-2 justify-end mt-4">
            <Button onClick={handleLogin}>Log In</Button>
          </div>
        </div>
      </Modal>
    );
  }

  if (!healthError && !expired) {
    return null;
  }

  if (healthError instanceof RedirectError || expired) {
    return null;
  } else {
    return (
      <div className="fixed top-0 left-0 z-[101] w-full text-xs mx-auto bg-gradient-to-r from-red-900 to-red-700 p-2 rounded-sm border-hidden text-neutral-50 dark:text-neutral-100">
        <p className="font-bold pb-1">The backend is currently unavailable.</p>

        <p className="px-1">
          If this is your initial setup or you just updated your Onyx
          deployment, this is likely because the backend is still starting up.
          Give it a minute or two, and then refresh the page. If that does not
          work, make sure the backend is setup and/or contact an administrator.
        </p>
      </div>
    );
  }
};
