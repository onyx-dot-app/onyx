"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { AuthLayouts } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";
import { markdown } from "@opal/utils";
import { usePHFeatureFlag, PHFeatureFlag } from "@/lib/analytics/hooks";

export default function UnavailablePage() {
  const router = useRouter();
  const signupDisabled = usePHFeatureFlag(PHFeatureFlag.SIGNUP_DISABLED);
  const { logoUrl, appName } = useSettings();

  useEffect(() => {
    if (!signupDisabled) router.replace("/auth/login" as Route);
  }, [signupDisabled, router]);

  if (!signupDisabled) return null;

  return (
    <AuthLayouts.Card
      title="Create account"
      description={`Get started with ${appName}`}
      bottomPrompt={markdown(
        "Already have an account? [Sign In](/auth/login?autoRedirectToSignup=false)"
      )}
      logoSrc={logoUrl}
    >
      <AuthLayouts.Message
        title="New account creation unavailable."
        description="New account creation will be available again soon."
      />
    </AuthLayouts.Card>
  );
}
