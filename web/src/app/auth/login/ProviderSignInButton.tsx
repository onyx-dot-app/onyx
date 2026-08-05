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
import { FcGoogle } from "react-icons/fc";
import Text from "@/refresh-components/texts/Text";
import { SSOProviderOption } from "@/lib/auth/types";

interface ProviderSignInButtonProps {
  provider: SSOProviderOption;
  nextUrl: string | null;
}

export default function ProviderSignInButton({
  provider,
  nextUrl,
}: ProviderSignInButtonProps) {
  const [isRedirecting, setIsRedirecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isGoogle = provider.providerType === "GOOGLE_OAUTH";

  async function handleClick() {
    if (isRedirecting) return;
    setIsRedirecting(true);
    setError(null);
    try {
      const url = nextUrl
        ? `${provider.authorizeUrl}?next=${encodeURIComponent(nextUrl)}`
        : provider.authorizeUrl;
      const res = await fetch(url, { credentials: "include" });
      if (!res.ok) {
        throw new Error(`Could not start sign-in (status ${res.status})`);
      }
      const data: { authorization_url?: string } = await res.json();
      if (!data.authorization_url) {
        throw new Error("Sign-in response was missing the authorization URL");
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
        icon={isGoogle ? FcGoogle : undefined}
        onClick={handleClick}
        disabled={isRedirecting}
      >
        {provider.displayName}
      </Button>
      {error && (
        <Text as="p" mainUiMuted className="text-status-error-05 mt-2">
          {error}
        </Text>
      )}
    </>
  );
}
