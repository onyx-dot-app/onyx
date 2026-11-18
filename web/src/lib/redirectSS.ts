import { NextRequest } from "next/server";

// Header the auth callback wrappers send to the API server so it builds
// callback and redirect URLs on the host the browser is on.
const FORWARDED_HOST_HEADER = "x-forwarded-host";

// Extra origins that also serve this deployment (comma-separated), such as a
// domain CNAMEd to WEB_DOMAIN. Must match the API server's ALTERNATE_WEB_DOMAINS.
function getAlternateWebDomains(): string[] {
  return (process.env.ALTERNATE_WEB_DOMAINS ?? "")
    .split(",")
    .map((domain) => domain.trim().replace(/\/+$/, ""))
    .filter((domain) => domain.length > 0);
}

function findAlternateWebDomain(request: NextRequest): string | null {
  const alternateWebDomains = getAlternateWebDomains();
  if (alternateWebDomains.length === 0) return null;

  for (const header of [FORWARDED_HOST_HEADER, "host"]) {
    // A proxy chain appends hosts; the first one is the browser's.
    const host = request.headers.get(header)?.split(",")[0]?.trim();
    if (!host) continue;
    const match = alternateWebDomains.find(
      (domain) => new URL(domain).host === host.toLowerCase()
    );
    if (match) return match;
  }
  return null;
}

export const getDomain = (request: NextRequest) => {
  // Use the WEB_DOMAIN env variable if set (required in production).
  // Never build a URL from X-Forwarded-* or Host headers — they can be
  // spoofed by an attacker to poison redirect URLs (host header poisoning).
  // A header may only select one of the configured alternate web domains.
  if (process.env.WEB_DOMAIN) {
    return findAlternateWebDomain(request) ?? process.env.WEB_DOMAIN;
  }

  // Fallback for local development: use Next.js's own origin.
  return request.nextUrl.origin;
};

// Headers for a server-side call to an API server auth endpoint, so the API
// server knows which web domain the browser is on.
export function getForwardedHostHeaders(
  request: NextRequest
): Record<string, string> {
  return { [FORWARDED_HOST_HEADER]: new URL(getDomain(request)).host };
}
