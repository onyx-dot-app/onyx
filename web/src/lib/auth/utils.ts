import type { AuthTypeMetadata } from "@/lib/auth/types";

// ---------------------------------------------------------------------------
// Auth URL helpers
// ---------------------------------------------------------------------------

export function getAuthUrl(
  multiTenant: boolean,
  nextUrl: string | null
): string | null {
  const params = new URLSearchParams({ redirect: "true" });
  if (nextUrl) params.set("next", nextUrl);

  return multiTenant ? `/api/auth/oauth/authorize?${params}` : null;
}

// ---------------------------------------------------------------------------
// Password predicate functions
// ---------------------------------------------------------------------------

export function passwordMeetsLengthRequirements(
  password: string,
  min: number,
  max: number
): boolean {
  return password.length >= min && password.length <= max;
}

export function passwordHasUppercase(password: string): boolean {
  return /[A-Z]/.test(password);
}

export function passwordHasLowercase(password: string): boolean {
  return /[a-z]/.test(password);
}

export function passwordHasDigit(password: string): boolean {
  return /\d/.test(password);
}

// Mirrors backend PASSWORD_SPECIAL_CHARS = "!@#$%^&*()_+-=[]{}|;:,.<>?"
export function passwordHasSpecialChar(password: string): boolean {
  return /[!@#$%^&*()_+\-=[\]{}|;:,.<>?]/.test(password);
}

// ---------------------------------------------------------------------------

/**
 * Validates a redirect URL to prevent Open Redirect vulnerabilities.
 * Only allows internal paths (relative URLs starting with /).
 *
 * Security: Rejects:
 * - External URLs (https://evil.com)
 * - Protocol-relative URLs (//evil.com)
 * - JavaScript URLs (javascript:alert(1))
 * - Data URLs (data:text/html,...)
 * - Absolute URLs with protocols
 */
export function validateInternalRedirect(
  url: string | null | undefined
): string | null {
  if (!url) {
    return null;
  }

  const trimmedUrl = url.trim();

  // The URL parser strips interior tab/CR/LF, so "/\t/evil.example" would slip
  // past the "//" check below and resolve to "//evil.example".
  for (let i = 0; i < trimmedUrl.length; i++) {
    const code = trimmedUrl.charCodeAt(i);
    if (code <= 0x1f || code === 0x7f) {
      return null;
    }
  }

  if (!trimmedUrl.startsWith("/")) {
    return null;
  }

  if (trimmedUrl.startsWith("//")) {
    return null;
  }

  // Rejects /javascript:alert(1), /http://evil.com, /data:text/html
  // but allows /chat?time=12:30:00, /admin#section:1
  if (trimmedUrl.match(/^[^?#]*:/)) {
    return null;
  }

  if (trimmedUrl.includes("\\")) {
    return null;
  }

  return trimmedUrl;
}

// ---------------------------------------------------------------------------
// SSO auto-start
// ---------------------------------------------------------------------------

/** True when the login page should start SSO on load: single-tenant, password
 * login off, exactly one provider, and the `autoRedirectToSso` flag not off. */
export function shouldAutoStartSso(
  authTypeMetadata: AuthTypeMetadata | null,
  autoRedirectToSso: boolean
): boolean {
  if (!autoRedirectToSso || !authTypeMetadata) return false;
  return (
    !authTypeMetadata.multiTenant &&
    !authTypeMetadata.passwordAuthEnabled &&
    (authTypeMetadata.ssoProviders ?? []).length === 1
  );
}

// ---------------------------------------------------------------------------
// Stale SSO state restart
// ---------------------------------------------------------------------------

// Callback errors a fresh login clears: a saved or shared IdP link, a login
// tab left open past the state's lifetime, or a second tab's flow.
const STALE_SSO_STATE_ERRORS: ReadonlySet<string> = new Set([
  "ACCESS_TOKEN_DECODE_ERROR",
  "ACCESS_TOKEN_ALREADY_EXPIRED",
  "OAUTH_INVALID_STATE",
]);

const SSO_RESTART_STORAGE_KEY = "onyx:sso-restart";
// Covers one IdP round trip: a restart that fails again inside it shows the
// error, and a later stale link in the same tab restarts again.
const SSO_RESTART_WINDOW_MS = 5 * 60 * 1000;

export function isStaleSsoStateError(code: string | null): boolean {
  return code !== null && STALE_SSO_STATE_ERRORS.has(code);
}

/** Claims this tab's automatic SSO restart. False inside the window or when
 * storage throws, since an unrecorded restart could loop. */
export function claimSsoRestart(): boolean {
  try {
    const storage = window.sessionStorage;
    const now = Date.now();
    const lastRestart = Number(storage.getItem(SSO_RESTART_STORAGE_KEY));
    if (now - lastRestart < SSO_RESTART_WINDOW_MS) return false;
    storage.setItem(SSO_RESTART_STORAGE_KEY, String(now));
    return true;
  } catch {
    return false;
  }
}
