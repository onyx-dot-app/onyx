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
 * With `autoStart` the flow begins on mount, for deployments where this
 * provider is the only way in. The button stays rendered as the retry path.
 *
 * Like SignInButton, this renders on the login page which is hit by headless
 * SSR requests, so browser globals stay out of the render path and live only in
 * startSignIn, reached from the effect and the click handler.
 *
 * IdPs refuse to render inside a frame, so when this page is embedded (the
 * Chrome extension's new tab page) the IdP opens in a new tab, falling back to
 * the top-level window if the popup is blocked.
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Text } from "@opal/components";
import { InputErrorText } from "@opal/layouts";
import { SvgGoogle } from "@opal/logos";
import { SSOProviderOption } from "@/lib/auth/types";
import { useTranslations } from "next-intl";

interface ProviderSignInButtonProps {
  provider: SSOProviderOption;
  nextUrl: string | null;
  /** Start the flow on mount as if the button had been clicked. */
  autoStart?: boolean;
}

function isFramed(): boolean {
  return window.top !== window.self && !!window.top;
}

/**
 * Opens the tab that will host the IdP. Must run synchronously in the click
 * handler: the authorize request that follows can outlast the transient user
 * activation `window.open` requires.
 */
function openIdpTab(): Window | null {
  return isFramed() ? window.open("about:blank", "_blank") : null;
}

/** Returns true when the IdP opened in a new tab and this page stays put. */
function navigateToIdp(url: string, idpTab: Window | null): boolean {
  if (!isFramed()) {
    window.location.href = url;
    return false;
  }
  if (idpTab && !idpTab.closed) {
    idpTab.location.href = url;
    return true;
  }
  if (window.open(url, "_blank")) return true;
  if (window.top) window.top.location.href = url;
  return false;
}

export default function ProviderSignInButton({
  provider,
  nextUrl,
  autoStart = false,
}: ProviderSignInButtonProps) {
  const t = useTranslations("auth");
  const [isRedirecting, setIsRedirecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Strict mode runs effects twice. A second authorize call would replace the
  // CSRF cookie that the first navigation's state was signed against.
  const autoStarted = useRef(false);

  const isGoogle = provider.providerType === "GOOGLE_OAUTH";

  const startSignIn = useCallback(
    async (idpTab: Window | null = null) => {
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
        if (navigateToIdp(data.authorization_url, idpTab)) {
          setIsRedirecting(false);
        }
      } catch (exc) {
        idpTab?.close();
        // Re-enable the button so the user can retry.
        setError(exc instanceof Error ? exc.message : String(exc));
        setIsRedirecting(false);
      }
    },
    [provider.authorizeUrl, nextUrl, t]
  );

  useEffect(() => {
    if (!autoStart || autoStarted.current) return;
    autoStarted.current = true;
    void startSignIn();
  }, [autoStart, startSignIn]);

  function handleClick() {
    if (isRedirecting) return;
    void startSignIn(openIdpTab());
  }

  return (
    <>
      {isRedirecting && (
        <Text font="main-ui-muted" color="text-03">
          {t("login.ssoRedirecting.text", { provider: provider.displayName })}
        </Text>
      )}
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
