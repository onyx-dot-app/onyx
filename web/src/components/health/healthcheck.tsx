"use client";

import { errorHandlingFetcher, FetchError, RedirectError } from "@/lib/fetcher";
import useSWR from "swr";
import { useRouter } from "next/navigation";
import { Modal } from "../Modal";

export const HealthCheckBanner = () => {
  const router = useRouter();
  const { error } = useSWR("/api/health", errorHandlingFetcher);

  if (!error) {
    return null;
  }

  if (error instanceof RedirectError) {
    return (
      <Modal
        width="w-1/4"
        className="overflow-y-hidden flex flex-col"
        title="You have been logged out!"
      >
        <div className="flex flex-col gap-y-4">
          <p className="text-lg ">
            You can click &quot;Log in&quot; to log back in! Apologies for the
            inconvenience.
          </p>
          <a
            href="/auth/login"
            className="w-full mt-4 mx-auto rounded-md text-neutral-200 py-2 bg-neutral-800 text-center hover:bg-neutral-700 animtate duration-300 transition-bg  "
          >
            Log in
          </a>
        </div>
      </Modal>
    );
  } else {
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
  }
};
