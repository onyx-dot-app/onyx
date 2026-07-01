"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import { useCurrentUser } from "@/lib/users/hooks";
import { useAuthTypeMetadata } from "@/lib/auth/hooks";
import { useSettings } from "@/lib/settings/hooks";
import { AuthType } from "@/lib/constants";
import { AuthLayouts } from "@opal/layouts";
import { toast } from "@/hooks/useToast";
import EmailPasswordForm from "@/sections/auth/EmailPasswordForm";
import SignInButton from "@/sections/auth/SignInButton";

function getAuthUrl(authType: AuthType): string | null {
  switch (authType) {
    case AuthType.GOOGLE_OAUTH:
    case AuthType.CLOUD:
      return `/api/auth/oauth/authorize?redirect=true`;
    case AuthType.OIDC:
      return `/api/auth/oidc/authorize?redirect=true`;
    case AuthType.SAML:
      return `/api/auth/saml/authorize?redirect=true`;
    default:
      return null;
  }
}

export default function JoinPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextUrl = searchParams.get("next");
  const defaultEmail = searchParams.get("email");

  const { user } = useCurrentUser();
  const { authTypeMetadata } = useAuthTypeMetadata();
  const { logoUrl } = useSettings();

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

  useEffect(() => {
    if (user === undefined) return;

    if (user && user.is_active && !user.is_anonymous_user) {
      if (authTypeMetadata.requiresVerification && !user.is_verified) {
        router.replace("/auth/email-verification" as Route);
      } else {
        router.replace("/app" as Route);
      }
      return;
    }

    const { authType } = authTypeMetadata;
    if (authType !== AuthType.BASIC && authType !== AuthType.CLOUD) {
      router.replace("/app" as Route);
    }
  }, [user, authTypeMetadata, router]);

  const isCloud = authTypeMetadata.authType === AuthType.CLOUD;
  const authUrl = getAuthUrl(authTypeMetadata.authType);

  return (
    <AuthLayouts.Card
      title="Re-authenticate to join team"
      description="Sign in to accept your team invitation."
      logoSrc={logoUrl}
    >
      {isCloud && authUrl && (
        <>
          <SignInButton authorizeUrl={authUrl} authType={AuthType.CLOUD} />
          <AuthLayouts.OrSeparator />
        </>
      )}

      <EmailPasswordForm
        label="join"
        shouldVerify={authTypeMetadata.requiresVerification}
        nextUrl={nextUrl}
        defaultEmail={defaultEmail}
      />
    </AuthLayouts.Card>
  );
}
