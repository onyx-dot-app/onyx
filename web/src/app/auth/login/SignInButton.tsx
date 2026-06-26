/**
 * SignInButton — renders the SSO / OAuth sign-in button on the login page.
 *
 * Renders SSO sign-in links for deployments using OIDC/SAML.
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

import { Button } from "@opal/components";
import { AuthType } from "@/lib/constants";

interface SignInButtonProps {
  authorizeUrl: string;
  authType: AuthType;
}

export default function SignInButton({
  authorizeUrl,
  authType,
}: SignInButtonProps) {
  let button: string | undefined;

  if (authType === AuthType.CLOUD) {
    button = "Continue with SSO";
  } else if (authType === AuthType.OIDC) {
    button = "Continue with OIDC SSO";
  } else if (authType === AuthType.SAML) {
    button = "Continue with SAML SSO";
  }

  if (!button) {
    throw new Error(`Unhandled authType: ${authType}`);
  }

  return (
    <Button prominence="primary" width="full" href={authorizeUrl}>
      {button}
    </Button>
  );
}
