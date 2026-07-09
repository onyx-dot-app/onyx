"use client";

import { AuthLayouts } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";
import { backToLoginOrSignupCopy, welcomeCardCopy } from "@/lib/auth/copies";
import { getAppLogo } from "@/lib/app/utils";

export default function SignupUnavailablePage() {
  const { logoUrl, appName } = useSettings();

  return (
    <AuthLayouts.Card
      {...welcomeCardCopy(appName)}
      bottomPrompt={backToLoginOrSignupCopy(true)}
      icon={getAppLogo(logoUrl)}
    >
      <AuthLayouts.Message
        title="New account creation unavailable."
        description="Existing accounts can still [sign in](/auth/login). New account creation will be available again soon."
      />
    </AuthLayouts.Card>
  );
}
