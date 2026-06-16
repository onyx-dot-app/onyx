"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { useAuthTypeMetadata } from "@/hooks/useAuthTypeMetadata";
import { AuthType } from "@/lib/constants";
import { ThreeDotsLoader } from "@/components/Loading";
import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import AuthErrorDisplay from "@/components/auth/AuthErrorDisplay";
import EmailPasswordForm from "@/app/auth/login/EmailPasswordForm";
import Text from "@/refresh-components/texts/Text";
import { Button, MessageCard, Text as OpalText } from "@opal/components";
import { SvgArrowRightCircle } from "@opal/icons";
import { markdown } from "@opal/utils";
import { usePHFeatureFlag, PHFeatureFlag } from "@/lib/analytics/hooks";

export default function SignupPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextUrl = searchParams.get("next");
  const defaultEmail = searchParams.get("email");
  const { user } = useCurrentUser();
  const { authTypeMetadata, isLoading } = useAuthTypeMetadata();
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

  if (isSignupDisabled) {
    return (
      <AuthFlowContainer authState="signup">
        <div className="flex w-full flex-col justify-start gap-6">
          <div className="w-full">
            <OpalText as="h2" font="heading-h2" color="text-05">
              Create account
            </OpalText>
            <OpalText as="p" font="main-ui-body" color="text-03">
              Get started with Onyx
            </OpalText>
          </div>

          <MessageCard
            title="New account creation unavailable."
            description={markdown(
              "Existing accounts can still [sign in](/auth/login?autoRedirectToSignup=false). New accounts creation will be available again soon. You can also try Onyx by [self-hosting](https://docs.onyx.app/deployment/overview)."
            )}
          />
        </div>
      </AuthFlowContainer>
    );
  }

  return (
    <AuthFlowContainer authState="signup">
      <AuthErrorDisplay
        searchParams={Object.fromEntries(searchParams.entries())}
      />

      <div className="flex w-full flex-col justify-start gap-6">
        <div className="w-full">
          <Text as="p" headingH2 text05>
            Create account
          </Text>
          <Text as="p" text03>
            Get started with Onyx
          </Text>
        </div>

        <EmailPasswordForm
          isSignup
          shouldVerify={authTypeMetadata.requiresVerification}
          nextUrl={nextUrl}
          defaultEmail={defaultEmail}
        />
      </div>
    </AuthFlowContainer>
  );
}
