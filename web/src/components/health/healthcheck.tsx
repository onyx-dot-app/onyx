"use client";

import { errorHandlingFetcher, RedirectError } from "@/lib/fetcher";
import useSWR from "swr";
import { Modal } from "../Modal";
import { useState } from "react";

export const HealthCheckBanner = ({
  secondsUntilExpiration,
}: {
  secondsUntilExpiration?: number | null;
}) => {
  const { error } = useSWR("/api/health", errorHandlingFetcher);
  const [expired, setExpired] = useState(false);

  if (secondsUntilExpiration !== null && secondsUntilExpiration !== undefined) {
    setTimeout(
      () => {
        setExpired(true);
      },
      secondsUntilExpiration * 1000 - 200
    );
  }

  if (!error && !expired) {
    return null;
  }

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
