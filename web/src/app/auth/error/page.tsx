"use client";

import { useEffect, useRef, useState } from "react";
import AuthErrorContent from "./AuthErrorContent";
import { useRouter, useSearchParams } from "next/navigation";
import { loginPath } from "@/lib/auth/paths";
import { claimSsoRestart, isStaleSsoStateError } from "@/lib/auth/utils";

function Page() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const error = searchParams?.get("error") || null;
  const isStale = isStaleSsoStateError(error);
  // Render nothing until the effect decides, so a restart never shows the error.
  const [restartSkipped, setRestartSkipped] = useState(false);
  // Dev StrictMode re-runs the effect, whose second run must not see its own claim.
  const restartStarted = useRef(false);

  useEffect(() => {
    if (!isStale || restartStarted.current) return;
    if (claimSsoRestart()) {
      restartStarted.current = true;
      router.replace(loginPath());
      return;
    }
    setRestartSkipped(true);
  }, [isStale, router]);

  if (isStale && !restartSkipped) return null;
  return <AuthErrorContent message={error} />;
}

export default Page;
