import { NextRequest } from "next/server";

export const getDomain = (request: NextRequest) => {
  // Use the WEB_DOMAIN env variable if set (required in production).
  // Never trust X-Forwarded-* headers from the request — they can be
  // spoofed by an attacker to poison redirect URLs (host header poisoning).
  if (process.env.WEB_DOMAIN) {
    return process.env.WEB_DOMAIN;
  }

  // Fallback for local development: use Next.js's own origin.
  return request.nextUrl.origin;
};
