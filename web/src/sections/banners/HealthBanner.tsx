"use client";

import useSWR from "swr";
import { errorHandlingFetcher, RedirectError } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { MessageCard } from "@opal/components";

export default function HealthBanner() {
  const { error } = useSWR(SWR_KEYS.health, errorHandlingFetcher);

  if (!error || error instanceof RedirectError) {
    return null;
  }

  return (
    <div className="fixed top-0 left-0 z-101 w-full p-3">
      <MessageCard
        variant="error"
        title="The backend is currently unavailable"
        description="If this is your initial setup or you just updated your Onyx deployment, this is likely because the backend is still starting up. Give it a minute or two, and then refresh the page. If that does not work, make sure the backend is setup and/or contact an administrator."
      />
    </div>
  );
}
