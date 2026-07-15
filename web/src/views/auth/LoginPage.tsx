"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import { AuthLayouts } from "@opal/layouts";
import { welcomeCardCopy } from "@/lib/auth/copies";
import { useSettings } from "@/lib/settings/hooks";
import { useCurrentUser } from "@/lib/users/hooks";
import { useAuthTypeMetadata, useAuthRedirect } from "@/lib/auth/hooks";
import { SignInButton, EmailPasswordForm } from "@/lib/auth/components";
import { AuthType } from "@/lib/auth/types";
import { NEXT_PUBLIC_AUTH_TYPE } from "@/lib/constants";
import { useSendAuthRequiredMessage } from "@/lib/extension/hooks";
import { getAuthUrl } from "@/lib/auth/utils";
import { markdown } from "@opal/utils";
import { Logo } from "@/lib/app/components";

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const autoRedirectDisabled =
    searchParams.get("disableAutoRedirect") === "true";
  const nextUrl = searchParams.get("next");
  const verified = searchParams.get("verified") === "true";
  const isFirstUser = searchParams.get("first_user") === "true";

  const { user } = useCurrentUser();
  const { authTypeMetadata } = useAuthTypeMetadata();
  const { appName } = useSettings();

  useSendAuthRequiredMessage();
  const isLoading = useAuthRedirect("login");

  const authUrl = getAuthUrl(NEXT_PUBLIC_AUTH_TYPE, nextUrl);
  const effectiveNextUrl =
    nextUrl ?? (isFirstUser ? "/app?new_team=true" : null);

  const isCloud = NEXT_PUBLIC_AUTH_TYPE === AuthType.CLOUD;
  const isBasic = NEXT_PUBLIC_AUTH_TYPE === AuthType.BASIC;
  const isSso =
    NEXT_PUBLIC_AUTH_TYPE === AuthType.GOOGLE_OAUTH ||
    NEXT_PUBLIC_AUTH_TYPE === AuthType.OIDC ||
    NEXT_PUBLIC_AUTH_TYPE === AuthType.SAML;

  useEffect(() => {
    if (isLoading) return;
    const isAuthenticated = !!user && user.is_active && !user.is_anonymous_user;
    if (isAuthenticated) return;

    if (authTypeMetadata.autoRedirect && authUrl && !autoRedirectDisabled) {
      router.replace(authUrl as Route);
      return;
    }

    // No users yet — send first-time visitors to signup, preserving nextUrl.
    if (
      !authTypeMetadata.hasUsers &&
      NEXT_PUBLIC_AUTH_TYPE === AuthType.BASIC
    ) {
      const params = nextUrl ? `?next=${encodeURIComponent(nextUrl)}` : "";
      router.replace(`/auth/signup${params}` as Route);
    }
  }, [
    isLoading,
    user,
    authTypeMetadata,
    authUrl,
    autoRedirectDisabled,
    nextUrl,
    router,
  ]);

  const signupUrl = nextUrl
    ? `/auth/signup?next=${encodeURIComponent(nextUrl)}`
    : "/auth/signup";
  const bottomPrompt = isSso
    ? "Need access? Reach out to your IT admin to get access."
    : markdown(`New to ${appName}? [Create an Account](${signupUrl})`);

  return (
    <AuthLayouts.Card
      {...welcomeCardCopy(appName)}
      bottomPrompt={bottomPrompt}
      icon={Logo}
    >
      {verified && (
        <AuthLayouts.Message
          messageType="success"
          title="Verification successful."
          description="Your email has been verified! Please sign in to continue."
        />
      )}

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
          label="submit"
          shouldVerify={isCloud}
          nextUrl={effectiveNextUrl}
        />
      )}
    </AuthLayouts.Card>
  );
}
