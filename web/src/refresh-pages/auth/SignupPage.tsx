"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { useAuthTypeMetadata } from "@/hooks/useAuthTypeMetadata";
import { AuthType } from "@/lib/constants";
import AuthFlowContainer from "@/refresh-pages/auth/AuthFlowContainer";
import AuthErrorDisplay from "@/components/auth/AuthErrorDisplay";
import EmailPasswordForm from "@/app/auth/login/EmailPasswordForm";
import { MessageCard } from "@opal/components";
import { markdown } from "@opal/utils";
import { usePHFeatureFlag, PHFeatureFlag } from "@/lib/analytics/hooks";

export default function SignupPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextUrl = searchParams.get("next");
  const defaultEmail = searchParams.get("email");
  const { user } = useCurrentUser();
  const { authTypeMetadata } = useAuthTypeMetadata();
  const isSignupDisabled = usePHFeatureFlag(PHFeatureFlag.SIGNUP_DISABLED);

  useEffect(() => {
    if (user === undefined) return;

    if (user && user.is_active && !user.is_anonymous_user) {
      if (!authTypeMetadata.requiresVerification || user.is_verified) {
        router.replace("/app");
      } else {
        router.replace("/auth/waiting-on-verification");
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
      <AuthFlowContainer
        title="Create account"
        description="Get started with Onyx"
        bottomPrompt={bottomPrompt}
      >
        <MessageCard
          title="New account creation unavailable."
          description={markdown(
            "Existing accounts can still [sign in](/auth/login?autoRedirectToSignup=false). New account creation will be available again soon. You can also try Onyx by [self-hosting](https://docs.onyx.app/deployment/overview)."
          )}
        />
      </AuthFlowContainer>
    );
  }

  return (
    <AuthFlowContainer
      title="Create account"
      description="Get started with Onyx"
      bottomPrompt={bottomPrompt}
    >
      <AuthErrorDisplay
        searchParams={Object.fromEntries(searchParams.entries())}
      />
      <EmailPasswordForm
        isSignup
        shouldVerify={authTypeMetadata.requiresVerification}
        nextUrl={nextUrl}
        defaultEmail={defaultEmail}
      />
    </AuthFlowContainer>
  );
}
