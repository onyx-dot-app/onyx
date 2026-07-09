"use client";

import { useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { useAuthTypeMetadata, useAuthRedirect } from "@/lib/auth/hooks";
import { useSettings } from "@/lib/settings/hooks";
import { AuthType } from "@/lib/auth/types";
import { AuthLayouts } from "@opal/layouts";
import { toast } from "@/hooks/useToast";
import EmailPasswordForm from "@/sections/auth/EmailPasswordForm";
import SignInButton from "@/sections/auth/SignInButton";
import { getAppLogo } from "@/lib/app/utils";

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
  const searchParams = useSearchParams();
  const nextUrl = searchParams.get("next");
  const defaultEmail = searchParams.get("email");

  const { authTypeMetadata } = useAuthTypeMetadata();
  const { logoUrl } = useSettings();

  useAuthRedirect("join");

  useEffect(() => {
    const error = searchParams.get("error");
    if (error) {
      toast.error(
        error === "Anonymous"
          ? "Your team does not have anonymous access enabled."
          : "An error occurred."
      );
      // Strip ?error from the URL so the toast doesn't re-fire on refresh.
      const params = new URLSearchParams(searchParams.toString());
      params.delete("error");
      const qs = params.size > 0 ? `?${params.toString()}` : "";
      window.history.replaceState(null, "", `${window.location.pathname}${qs}`);
    }
  }, [searchParams]);

  const isCloud = authTypeMetadata.authType === AuthType.CLOUD;
  const authUrl = getAuthUrl(authTypeMetadata.authType);

  return (
    <AuthLayouts.Card
      title="Re-authenticate to join team"
      description="Sign in to accept your team invitation."
      icon={getAppLogo(logoUrl)}
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
