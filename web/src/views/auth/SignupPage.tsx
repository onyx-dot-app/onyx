"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCurrentUser } from "@/lib/users/hooks";
import { useAuthTypeMetadata } from "@/lib/auth/hooks";
import { useSettings } from "@/lib/settings/hooks";
import { AuthType } from "@/lib/constants";
import { AuthLayouts } from "@opal/layouts";
import AuthErrorDisplay from "@/components/auth/AuthErrorDisplay";
import EmailPasswordForm from "@/sections/auth/EmailPasswordForm";
import { markdown } from "@opal/utils";
import { usePHFeatureFlag, PHFeatureFlag } from "@/lib/analytics/hooks";

export default function SignupPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextUrl = searchParams.get("next");
  const defaultEmail = searchParams.get("email");
  const { user } = useCurrentUser();
  const { authTypeMetadata } = useAuthTypeMetadata();
  const { logoUrl, appName } = useSettings();
  const isSignupDisabled = usePHFeatureFlag(PHFeatureFlag.SIGNUP_DISABLED);

  useEffect(() => {
    if (user === undefined) return;

    if (user && user.is_active && !user.is_anonymous_user) {
      if (!authTypeMetadata.requiresVerification || user.is_verified) {
        router.replace("/app");
      } else {
        router.replace("/auth/email-verification");
      }
      return;
    }

    if (authTypeMetadata.authType !== AuthType.BASIC) {
      router.replace("/app");
    }
  }, [user, authTypeMetadata, router]);

  const bottomPrompt = markdown(
    "Already have an account? [Sign In](/auth/login?autoRedirectToSignup=false)"
  );

  if (isSignupDisabled) {
    return (
      <AuthLayouts.Card
        title="Create account"
        description={`Get started with ${appName}`}
        bottomPrompt={bottomPrompt}
        logoSrc={logoUrl}
      >
        <AuthLayouts.Message
          title="New account creation unavailable."
          description="New account creation will be available again soon."
        />
      </AuthLayouts.Card>
    );
  }

  return (
    <AuthLayouts.Card
      title="Create account"
      description={`Get started with ${appName}`}
      bottomPrompt={bottomPrompt}
      logoSrc={logoUrl}
    >
      <AuthErrorDisplay
        searchParams={Object.fromEntries(searchParams.entries())}
      />
      <EmailPasswordForm
        label="create"
        shouldVerify={authTypeMetadata.requiresVerification}
        nextUrl={nextUrl}
        defaultEmail={defaultEmail}
      />
    </AuthLayouts.Card>
  );
}
