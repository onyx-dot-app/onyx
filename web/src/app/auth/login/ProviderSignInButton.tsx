/**
 * ProviderSignInButton: one login button for a DB-backed SSO provider.
 *
 * /authorize returns JSON {authorization_url} rather than redirecting. For
 * OIDC/Google it also sets the CSRF/PKCE cookies on that response, so the fetch
 * must run in the browser (credentials included) to land those cookies on the
 * client that completes the flow. A server component fetching it would land them
 * on the wrong client. SAML sets no cookies but returns the same shape, so it
 * takes the same path.
 *
 * Like SignInButton, this renders on the login page which is hit by headless
 * SSR requests, so browser globals stay out of the render path and live only in
 * the click handler.
 */

"use client";

import { useState } from "react";
import { Button } from "@opal/components";
import { InputErrorText } from "@opal/layouts";
import { SvgGoogle } from "@opal/logos";
import { SSOProviderOption } from "@/lib/auth/types";
import { useTranslations } from "next-intl";

interface ProviderSignInButtonProps {
  provider: SSOProviderOption;
  nextUrl: string | null;
}

export default function ProviderSignInButton({
  provider,
  nextUrl,
}: ProviderSignInButtonProps) {
  const t = useTranslations("auth");
  const [isRedirecting, setIsRedirecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isGoogle = provider.providerType === "GOOGLE_OAUTH";

  async function handleClick() {
    if (isRedirecting) return;
    setIsRedirecting(true);
    setError(null);
    try {
      // The authorize URL may already carry a query (the workspace pin on
      // cloud), so `next` has to be appended as a parameter, not concatenated.
      const url = new URL(provider.authorizeUrl, window.location.origin);
      if (nextUrl) url.searchParams.set("next", nextUrl);
      const res = await fetch(url.toString(), { credentials: "include" });
      if (!res.ok) {
        throw new Error(
          t("login.ssoStartFailed.error", { status: res.status })
        );
      }
      const data: { authorization_url?: string } = await res.json();
      if (!data.authorization_url) {
        throw new Error(t("login.ssoMissingAuthUrl.error"));
      }
      window.location.href = data.authorization_url;
    } catch (exc) {
      // Re-enable the button so the user can retry.
      setError(exc instanceof Error ? exc.message : String(exc));
      setIsRedirecting(false);
    }
  }

  return (
    <>
      <Button
        prominence={isGoogle ? "secondary" : "primary"}
        width="full"
        icon={isGoogle ? SvgGoogle : undefined}
        onClick={handleClick}
        disabled={isRedirecting}
      >
        {provider.displayName}
      </Button>
      {error && <InputErrorText>{error}</InputErrorText>}
    </>
  );
}
