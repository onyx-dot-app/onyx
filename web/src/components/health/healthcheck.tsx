"use client";

import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR from "swr";

export const HealthCheckBanner = () => {
  const { error } = useSWR("/api/health", errorHandlingFetcher);
  if (!error) {
    return null;
  }

  return (
    <div className="text-xs mx-auto bg-gradient-to-r from-red-900 to-red-700 p-2 rounded-sm border-hidden text-gray-300">
      <p className="font-bold pb-1">The backend is currently unavailable.</p>

      <p className="px-1">
        If this is your initial setup or you just updated your Danswer
        deployment, this is likely because the backend is still starting up.
        Give it a minute or two, and then refresh the page. If that does not
        work, make sure the backend is setup and/or contact an administrator.
      </p>
    </div>
  );
};
