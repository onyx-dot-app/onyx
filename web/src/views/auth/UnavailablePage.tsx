"use client";

import { AuthLayouts } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";
import { markdown } from "@opal/utils";

export default function UnavailablePage() {
  const { logoUrl, appName } = useSettings();

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
