"use client";

import { AuthLayouts } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";
import { backToLoginOrSignupCopy, welcomeCardCopy } from "@/lib/auth/copies";
import { useAppLogo } from "@/lib/app/hooks";

export default function SignupUnavailablePage() {
  const { appName } = useSettings();
  const icon = useAppLogo(true);

  return (
    <AuthLayouts.Card
      {...welcomeCardCopy(appName)}
      bottomPrompt={backToLoginOrSignupCopy(true)}
      icon={icon}
    >
      <AuthLayouts.Message
        title="New account creation unavailable."
        description="Existing accounts can still [sign in](/auth/login). New account creation will be available again soon."
      />
    </AuthLayouts.Card>
  );
}
