"use client";

import { AuthLayouts } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";
import { backToLoginOrSignupCopy, welcomeCardCopy } from "@/lib/auth/copies";
import { Logo } from "@/lib/app/components";

export default function SignupUnavailablePage() {
  const { appName } = useSettings();

  return (
    <AuthLayouts.Card
      {...welcomeCardCopy(appName)}
      bottomPrompt={backToLoginOrSignupCopy(true)}
      icon={Logo}
    >
      <AuthLayouts.Message
        title="New account creation unavailable."
        description="Existing accounts can still [sign in](/auth/login). New account creation will be available again soon."
      />
    </AuthLayouts.Card>
  );
}
