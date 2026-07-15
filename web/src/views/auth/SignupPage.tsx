"use client";

import { useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { useAuthTypeMetadata, useAuthRedirect } from "@/lib/auth/hooks";
import { useSettings } from "@/lib/settings/hooks";
import { AuthLayouts } from "@opal/layouts";
import { toast } from "@/hooks/useToast";
import { SignInButton, EmailPasswordForm } from "@/lib/auth/components";
import { AuthType } from "@/lib/auth/types";
import { NEXT_PUBLIC_AUTH_TYPE } from "@/lib/constants";
import { getAuthUrl } from "@/lib/auth/utils";
import { markdown } from "@opal/utils";
import { Logo } from "@/lib/app/components";

export default function SignupPage() {
  const searchParams = useSearchParams();
  const nextUrl = searchParams.get("next");
  const defaultEmail = searchParams.get("email");
  const { authTypeMetadata } = useAuthTypeMetadata();
  const { appName } = useSettings();

  useAuthRedirect("signup");

  useEffect(() => {
    const error = searchParams.get("error");
    if (error) {
      toast.error(
        error === "Anonymous"
          ? "Your team does not have anonymous access enabled."
          : "An error occurred."
      );
    }
  }, [searchParams]);

  const authUrl = getAuthUrl(NEXT_PUBLIC_AUTH_TYPE, nextUrl);
  const isCloud = NEXT_PUBLIC_AUTH_TYPE === AuthType.CLOUD;
  const isBasic = NEXT_PUBLIC_AUTH_TYPE === AuthType.BASIC;
  const isSso =
    NEXT_PUBLIC_AUTH_TYPE === AuthType.GOOGLE_OAUTH ||
    NEXT_PUBLIC_AUTH_TYPE === AuthType.OIDC ||
    NEXT_PUBLIC_AUTH_TYPE === AuthType.SAML;

  const loginUrl = nextUrl
    ? `/auth/login?next=${encodeURIComponent(nextUrl)}`
    : "/auth/login";
  const bottomPrompt = isSso
    ? "Need access? Reach out to your IT admin to get access."
    : markdown(`Already have an account? [Sign In](${loginUrl})`);

  return (
    <AuthLayouts.Card
      title="Create account"
      description={`Get started with ${appName}`}
      bottomPrompt={bottomPrompt}
      icon={Logo}
    >
      {authUrl && !isCloud && !isBasic && (
        <SignInButton authorizeUrl={authUrl} authType={NEXT_PUBLIC_AUTH_TYPE} />
      )}

      {isCloud && authUrl && (
        <>
          <SignInButton
            authorizeUrl={authUrl}
            authType={NEXT_PUBLIC_AUTH_TYPE}
          />
          <AuthLayouts.OrSeparator />
        </>
      )}

      {(isCloud || isBasic) && (
        <EmailPasswordForm
          label="create"
          shouldVerify={authTypeMetadata.requiresVerification}
          nextUrl={nextUrl}
          defaultEmail={defaultEmail}
        />
      )}
    </AuthLayouts.Card>
  );
}
