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
import { AuthType } from "@/lib/auth/types";
import { SvgGoogle } from "@opal/logos";
import type { IconProps } from "@opal/types";
import { useCaptcha } from "@/lib/hooks/useCaptcha";
import { toast } from "@/hooks/useToast";
import { verifyCaptchaForOAuth } from "@/lib/auth/svc";

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

  let button: string | undefined;
  let icon: React.FunctionComponent<IconProps> | undefined;

  if (authType === AuthType.GOOGLE_OAUTH || authType === AuthType.CLOUD) {
    button = "Continue with Google";
    icon = SvgGoogle;
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
    // Stays true on the success branch so the button remains disabled until
    // the browser actually begins unloading for the OAuth redirect — prevents
    // a double-click window between `window.location.href = ...` and unload.
    let navigating = false;
    try {
      const token = await getCaptchaToken("oauth");
      if (!token) {
        toast.error("grecaptcha.execute returned no token");
        return;
      }
      await verifyCaptchaForOAuth(token);
      navigating = true;
      window.location.href = authorizeUrl;
    } catch (exc) {
      toast.error(exc instanceof Error ? exc.message : String(exc));
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
    <Button
      prominence="secondary"
      width="full"
      icon={icon}
      href={intercepted ? undefined : authorizeUrl}
      onClick={intercepted ? handleClick : undefined}
      disabled={isVerifying}
    >
      {button}
    </Button>
  );
}
