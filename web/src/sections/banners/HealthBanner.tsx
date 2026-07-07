"use client";

import { useState } from "react";
import useSWR from "swr";
import { useRouter } from "next/navigation";
import { errorHandlingFetcher, RedirectError } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  useCustomTokenRefresh,
  useSessionWatcher,
  useTokenExpiry,
} from "@/lib/auth/hooks";
import { useCurrentUser } from "@/lib/users/hooks";
import { getExtensionContext } from "@/lib/extension/utils";
import { MessageCard } from "@opal/components";
import LoggedOutModal from "@/sections/modals/LoggedOutModal";

export default function HealthBanner() {
  const router = useRouter();
  const { error } = useSWR(SWR_KEYS.health, errorHandlingFetcher);
  const { user, mutateUser, userError } = useCurrentUser();
  const { expired, setupExpirationTimeout } = useTokenExpiry(user);
  useCustomTokenRefresh(user, setupExpirationTimeout, mutateUser);
  const { sessionEnded } = useSessionWatcher({
    user,
    userError,
    healthError: error,
    expired,
  });
  const [dismissed, setDismissed] = useState(false);

  function handleLogin() {
    setDismissed(true);
    const { isExtension } = getExtensionContext();
    if (isExtension) {
      window.open(
        window.location.origin + "/auth/login",
        "_blank",
        "noopener,noreferrer"
      );
    } else {
      router.push("/auth/login");
    }
  }

  if (sessionEnded && !dismissed) {
    return <LoggedOutModal onLogin={handleLogin} />;
  }

  if (!error || error instanceof RedirectError || expired) {
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
