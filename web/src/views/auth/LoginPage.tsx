"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import { AuthLayouts } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { useAuthTypeMetadata } from "@/lib/auth/hooks";
import SignInButton from "@/sections/auth/SignInButton";
import EmailPasswordForm from "@/sections/auth/EmailPasswordForm";
import { AuthType, NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED } from "@/lib/constants";
import { useSendAuthRequiredMessage } from "@/lib/extension/utils";
import { Button, MessageCard } from "@opal/components";
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
  const autoRedirectToSignupDisabled =
    searchParams.get("autoRedirectToSignup") === "false";
  const nextUrl = searchParams.get("next");
  const verified = searchParams.get("verified") === "true";
  const isFirstUser = searchParams.get("first_user") === "true";

  const { user } = useCurrentUser();
  const { authTypeMetadata } = useAuthTypeMetadata();
  const { logoUrl, appName } = useSettings();

  useSendAuthRequiredMessage();

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
    if (user === undefined) return;

    if (
      !authTypeMetadata.hasUsers &&
      !autoRedirectToSignupDisabled &&
      authTypeMetadata.authType === AuthType.BASIC
    ) {
      router.replace("/auth/signup" as Route);
      return;
    }

    if (user && user.is_active && !user.is_anonymous_user) {
      if (authTypeMetadata.requiresVerification && !user.is_verified) {
        router.replace("/auth/email-verification" as Route);
      } else {
        router.replace("/app?from=login" as Route);
      }
      return;
    }

    if (authTypeMetadata.autoRedirect && authUrl && !autoRedirectDisabled) {
      router.replace(authUrl as Route);
    }
  }, [
    user,
    authTypeMetadata,
    authUrl,
    autoRedirectDisabled,
    autoRedirectToSignupDisabled,
    router,
  ]);

  const bottomPrompt = isSso
    ? "Need access? Reach out to your IT admin to get access."
    : markdown(`New to ${appName}? [Create an Account](/auth/signup)`);

  return (
    <AuthLayouts.Card
      title={`Welcome to ${appName}`}
      description="Your AI platform for work"
      bottomPrompt={bottomPrompt}
      logoSrc={logoUrl}
    >
      {verified && (
        <MessageCard
          variant="success"
          title="Your email has been verified! Please sign in to continue."
        />
      )}

      {authUrl && !isCloud && !isBasic && (
        <SignInButton
          authorizeUrl={authUrl}
          authType={authTypeMetadata.authType}
        />
      )}

      {isCloud && (
        <>
          {authUrl && (
            <>
              <SignInButton
                authorizeUrl={authUrl}
                authType={authTypeMetadata.authType}
              />
              <AuthLayouts.OrSeparator />
            </>
          )}
          <EmailPasswordForm
            label="submit"
            shouldVerify
            nextUrl={effectiveNextUrl}
          />
          {NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED && (
            <Button href="/auth/forgot-password">Reset Password</Button>
          )}
        </>
      )}

      {isBasic && (
        <EmailPasswordForm label="submit" nextUrl={effectiveNextUrl} />
      )}
    </AuthLayouts.Card>
  );
}
