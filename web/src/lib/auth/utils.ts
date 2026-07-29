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
