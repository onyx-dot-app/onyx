"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import { AuthLayouts } from "@opal/layouts";
import { welcomeCardCopy } from "@/lib/auth/copies";
import { useSettings } from "@/lib/settings/hooks";
import { useCurrentUser } from "@/lib/users/hooks";
import { useAuthTypeMetadata } from "@/lib/auth/hooks";
import SignInButton from "@/sections/auth/SignInButton";
import EmailPasswordForm from "@/sections/auth/EmailPasswordForm";
import { AuthType } from "@/lib/auth/types";
import { useSendAuthRequiredMessage } from "@/lib/extension/hooks";
import { useAuthRedirect } from "@/lib/auth/hooks";
import { useAppLogo } from "@/lib/app/hooks";
import { markdown } from "@opal/utils";

function getAuthUrl(authType: AuthType, nextUrl: string | null): string | null {
  const params = new URLSearchParams({ redirect: "true" });
  if (nextUrl) params.set("next", nextUrl);

  switch (authType) {
    case AuthType.BASIC:
      return null;
    case AuthType.GOOGLE_OAUTH:
    case AuthType.CLOUD:
      return `/api/auth/oauth/authorize?${params}`;
    case AuthType.OIDC:
      return `/api/auth/oidc/authorize?${params}`;
    case AuthType.SAML:
      return `/api/auth/saml/authorize?${params}`;
    default:
      return null;
  }
}

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
  const icon = useAppLogo(true);

  useSendAuthRequiredMessage();
  const isLoading = useAuthRedirect("login");

  const authUrl = getAuthUrl(authTypeMetadata.authType, nextUrl);
  const effectiveNextUrl =
    nextUrl ?? (isFirstUser ? "/app?new_team=true" : null);

  const isCloud = authTypeMetadata.authType === AuthType.CLOUD;
  const isBasic = authTypeMetadata.authType === AuthType.BASIC;
  const isSso =
    authTypeMetadata.authType === AuthType.GOOGLE_OAUTH ||
    authTypeMetadata.authType === AuthType.OIDC ||
    authTypeMetadata.authType === AuthType.SAML;

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
      authTypeMetadata.authType === AuthType.BASIC
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
      icon={icon}
    >
      {verified && (
        <AuthLayouts.Message
          messageType="success"
          title="Verification successful."
          description="Your email has been verified! Please sign in to continue."
        />
      )}

      {authUrl && !isCloud && !isBasic && (
        <SignInButton
          authorizeUrl={authUrl}
          authType={authTypeMetadata.authType}
        />
      )}

      {isCloud && authUrl && (
        <>
          <SignInButton
            authorizeUrl={authUrl}
            authType={authTypeMetadata.authType}
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
