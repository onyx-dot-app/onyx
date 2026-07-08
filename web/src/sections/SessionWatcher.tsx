"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useSessionWatcher } from "@/lib/auth/hooks";
import { useCurrentUser } from "@/lib/users/hooks";
import { getExtensionContext } from "@/lib/extension/utils";
import LoggedOutModal from "@/sections/modals/LoggedOutModal";

export default function SessionWatcher() {
  const router = useRouter();
  const { user, mutateUser, userError } = useCurrentUser();
  const { sessionEnded } = useSessionWatcher({ user, userError, mutateUser });
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

  return null;
}
