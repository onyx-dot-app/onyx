"use client";

import { errorHandlingFetcher, RedirectError } from "@/lib/fetcher";
import useSWR from "swr";
import { Modal } from "../Modal";
import { useCallback, useEffect, useState } from "react";
import { getSecondsUntilExpiration } from "@/lib/time";
import { User } from "@/lib/types";
import { mockedRefreshToken, refreshToken } from "./refreshUtils";
import { NEXT_PUBLIC_CUSTOM_REFRESH_URL } from "@/lib/constants";

export const HealthCheckBanner = () => {
  const { error } = useSWR("/api/health", errorHandlingFetcher);
  const [expired, setExpired] = useState(false);
  const [secondsUntilExpiration, setSecondsUntilExpiration] = useState<
    number | null
  >(null);
  const { data: user, mutate: mutateUser } = useSWR<User>(
    "/api/me",
    errorHandlingFetcher
  );

  const updateExpirationTime = useCallback(async () => {
    const updatedUser = await mutateUser();

    if (updatedUser) {
      const seconds = getSecondsUntilExpiration(updatedUser);
      setSecondsUntilExpiration(seconds);
      console.debug(`Updated seconds until expiration:! ${seconds}`);
    }
  }, [mutateUser]);

  useEffect(() => {
    updateExpirationTime();
  }, [user, updateExpirationTime]);

  useEffect(() => {
    if (NEXT_PUBLIC_CUSTOM_REFRESH_URL) {
      const refreshUrl = NEXT_PUBLIC_CUSTOM_REFRESH_URL;
      let refreshIntervalId: NodeJS.Timer;
      let expireTimeoutId: NodeJS.Timeout;

      const attemptTokenRefresh = async () => {
        let retryCount = 0;
        const maxRetries = 3;

        while (retryCount < maxRetries) {
          try {
            // NOTE: This is a mocked refresh token for testing purposes.
            // const refreshTokenData = mockedRefreshToken();

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
            await new Promise((resolve) => setTimeout(resolve, 4000));

            await mutateUser(undefined, { revalidate: true });
            updateExpirationTime();
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

      const scheduleRefreshAndExpire = () => {
        if (secondsUntilExpiration !== null) {
          const refreshInterval = 60 * 15; // 15 mins
          refreshIntervalId = setInterval(
            attemptTokenRefresh,
            refreshInterval * 1000
          );

          const timeUntilExpire = (secondsUntilExpiration + 10) * 1000;
          expireTimeoutId = setTimeout(() => {
            console.debug("Session expired. Setting expired state to true.");
            setExpired(true);
          }, timeUntilExpire);

          // if we're going to timeout before the next refresh, kick off a refresh now!
          if (secondsUntilExpiration < refreshInterval) {
            attemptTokenRefresh();
          }
        }
      };

      scheduleRefreshAndExpire();

      return () => {
        clearInterval(refreshIntervalId);
        clearTimeout(expireTimeoutId);
      };
    }
  }, [secondsUntilExpiration, user, mutateUser, updateExpirationTime]);

  if (!error && !expired) {
    return null;
  }

  console.debug(
    `Rendering HealthCheckBanner. Error: ${error}, Expired: ${expired}`
  );

  if (error instanceof RedirectError || expired) {
    return (
      <Modal
        width="w-1/4"
        className="overflow-y-hidden flex flex-col"
        title="You've been logged out"
      >
        <div className="flex flex-col gap-y-4">
          <p className="text-sm">
            Your session has expired. Please log in again to continue.
          </p>
          <a
            href="/auth/login"
            className="w-full mt-4 mx-auto rounded-md text-text-200 py-2 bg-background-900 text-center hover:bg-emphasis animtate duration-300 transition-bg"
          >
            Log in
          </a>
        </div>
      </Modal>
    );
  } else {
    return (
      <div className="fixed top-0 left-0 z-[101] w-full text-xs mx-auto bg-gradient-to-r from-red-900 to-red-700 p-2 rounded-sm border-hidden text-text-200">
        <p className="font-bold pb-1">The backend is currently unavailable.</p>

        <p className="px-1">
          If this is your initial setup or you just updated your Danswer
          deployment, this is likely because the backend is still starting up.
          Give it a minute or two, and then refresh the page. If that does not
          work, make sure the backend is setup and/or contact an administrator.
        </p>
      </div>
    );
  }
};
