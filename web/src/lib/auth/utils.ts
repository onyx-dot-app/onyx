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
