"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { AuthLayouts } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";
import { usePHFeatureFlag, PHFeatureFlag } from "@/lib/analytics/hooks";
import { backToLoginOrSignupCopy, welcomeCardCopy } from "@/lib/auth/copies";

export default function SignupUnavailablePage() {
  const router = useRouter();
  const signupDisabled = usePHFeatureFlag(PHFeatureFlag.SIGNUP_DISABLED);
  const { logoUrl, appName } = useSettings();

  useEffect(() => {
    if (signupDisabled) return;
    router.replace("/auth/login" as Route);
  }, [signupDisabled, router]);

  if (!signupDisabled) return null;

  return (
    <AuthLayouts.Card
      {...welcomeCardCopy(appName)}
      bottomPrompt={backToLoginOrSignupCopy(true)}
      logoSrc={logoUrl}
    >
      <AuthLayouts.Message
        title="New account creation unavailable."
        description="Existing accounts can still [sign in](/auth/login). New account creation will be available again soon."
      />
    </AuthLayouts.Card>
  );
}
