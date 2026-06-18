/**
 * SignInButton — renders the SSO / OAuth sign-in button on the login page.
 *
 * When reCAPTCHA is enabled for this deployment (NEXT_PUBLIC_RECAPTCHA_SITE_KEY
 * set at build time), the Google/OIDC/SAML OAuth click is intercepted to
 * (1) fetch a reCAPTCHA v3 token for the "oauth" action, (2) POST it to
 * /api/auth/captcha/oauth-verify which sets a signed HttpOnly cookie on the
 * response, and (3) then navigate to the authorize URL. The cookie is sent
 * automatically on the subsequent Google redirect back to our callback,
 * where the backend middleware verifies it.
 *
 * IMPORTANT: This component is rendered as part of the /auth/login page, which
 * is used in healthcheck and monitoring flows that issue headless (non-browser)
 * requests (e.g. `curl`). During server-side rendering of those requests,
 * browser-only globals like `window`, `document`, `navigator`, etc. are NOT
 * available. Even though this file is marked "use client", Next.js still
 * executes the component body on the server during SSR — only hooks like
 * `useEffect` are skipped.
 *
 * Do NOT reference `window` or other browser APIs in the render path of this
 * component. If you need browser globals, gate them behind `useEffect` or
 * `typeof window !== "undefined"` checks inside callbacks/effects — but be
 * aware that Turbopack may optimise away bare `typeof window` guards in the
 * SSR bundle, so prefer `useEffect` for safety.
 */

"use client";

import { useState } from "react";
import { Button } from "@opal/components";
import { AuthType } from "@/lib/constants";
import { FcGoogle } from "react-icons/fc";
import type { IconProps } from "@opal/types";
import { useCaptcha } from "@/lib/hooks/useCaptcha";
import Text from "@/refresh-components/texts/Text";

interface SignInButtonProps {
  authorizeUrl: string;
  authType: AuthType;
}

export default function SignInButton({
  authorizeUrl,
  authType,
}: SignInButtonProps) {
  const { getCaptchaToken, isCaptchaEnabled } = useCaptcha();
  const [isVerifying, setIsVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  let button: string | undefined;
  let icon: React.FunctionComponent<IconProps> | undefined;

  if (authType === AuthType.GOOGLE_OAUTH || authType === AuthType.CLOUD) {
    button = "Continue with Google";
    icon = FcGoogle;
  } else if (authType === AuthType.OIDC) {
    button = "Continue with OIDC SSO";
  } else if (authType === AuthType.SAML) {
    button = "Continue with SAML SSO";
  }

  if (!button) {
    throw new Error(`Unhandled authType: ${authType}`);
  }

  async function handleClick(e: React.MouseEvent) {
    e.preventDefault();
    if (isVerifying) return;
    setIsVerifying(true);
    setError(null);
    // Stays true on the success branch so the button remains disabled until
    // the browser actually begins unloading for the OAuth redirect — prevents
    // a double-click window between `window.location.href = ...` and unload.
    let navigating = false;
    try {
      const token = await getCaptchaToken("oauth");
      if (!token) {
        // eslint-disable-next-line no-console
        console.error(
          "Captcha: grecaptcha.execute returned no token. The widget may not have loaded yet."
        );
        setError("grecaptcha.execute returned no token");
        return;
      }
      const res = await fetch("/api/auth/captcha/oauth-verify", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        // eslint-disable-next-line no-console
        console.error(
          `Captcha verify rejected: status=${res.status} detail=${
            body.detail ?? "(none)"
          }`
        );
        setError(
          "Captcha verification failed. Please refresh your browser and try again."
        );
        return;
      }
      navigating = true;
      window.location.href = authorizeUrl;
    } catch (exc) {
      // eslint-disable-next-line no-console
      console.error("Captcha verify request failed", exc);
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      if (!navigating) setIsVerifying(false);
    }
  }

  // Only the Google OAuth callback is gated by CaptchaCookieMiddleware on the
  // backend. OIDC/SAML callbacks have no cookie requirement, so running the
  // reCAPTCHA interception for them is wasted friction — and worse, a failed
  // captcha would block the sign-in entirely.
  const intercepted =
    isCaptchaEnabled &&
    (authType === AuthType.GOOGLE_OAUTH || authType === AuthType.CLOUD);

  return (
    <>
      <Button
        prominence={
          authType === AuthType.GOOGLE_OAUTH || authType === AuthType.CLOUD
            ? "secondary"
            : "primary"
        }
        width="full"
        icon={icon}
        href={intercepted ? undefined : authorizeUrl}
        onClick={intercepted ? handleClick : undefined}
        disabled={isVerifying}
      >
        {button}
      </Button>
      {error && (
        <Text as="p" mainUiMuted className="text-status-error-05 mt-2">
          {error}
        </Text>
      )}
    </>
  );
}
