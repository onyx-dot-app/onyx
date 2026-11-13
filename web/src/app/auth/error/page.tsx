"use client";

import { useNavigation, useSearchParams } from "@opal/navigation";
import { useEffect, useRef, useState } from "react";
import AuthErrorContent from "./AuthErrorContent";
import { loginPath } from "@/lib/auth/paths";
import { claimSsoRestart, isStaleSsoStateError } from "@/lib/auth/utils";

function Page() {
  const navigation = useNavigation();
  const searchParams = useSearchParams();
  const error = searchParams.get("error") || null;
  const isStale = isStaleSsoStateError(error);
  // Render nothing until the effect decides, so a restart never shows the error.
  const [restartSkipped, setRestartSkipped] = useState(false);
  // Dev StrictMode re-runs the effect, whose second run must not see its own claim.
  const restartStarted = useRef(false);
  // `go` drops `?error` from the URL before the login page renders; stay blank
  // until it does.
  const [restarting, setRestarting] = useState(false);

  useEffect(() => {
    if (!isStale || restartStarted.current) return;
    if (claimSsoRestart()) {
      restartStarted.current = true;
      setRestarting(true);
      navigation.go(loginPath(), { replace: true });
      return;
    }
    setRestartSkipped(true);
  }, [isStale, navigation]);

  if (restarting || (isStale && !restartSkipped)) return null;
  return <AuthErrorContent message={error} />;
}

export default Page;
