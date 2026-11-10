import type { NextResponse } from "next/server";

// The CSP is emitted at runtime, not in next.config.js `headers()` (which is baked
// into the build), so WEB_FRAME_PROTECTION_ENABLED is read at runtime and
// applies on restart without a rebuild.
//
// frame-ancestors controls who may embed Onyx in an <iframe>. On by default;
// WEB_FRAME_PROTECTION_ENABLED=false drops it so any origin may frame Onyx.
// chrome-extension:/moz-extension: are app-wide (the extension iframes every
// route, not just /nrf) and cover both Chromium and Firefox builds.
// X-Frame-Options is omitted: it can't express the extension allowance and
// modern browsers honor frame-ancestors.
const frameProtectionEnabled =
  process.env.WEB_FRAME_PROTECTION_ENABLED?.toLowerCase() !== "false";
const FRAME_CSP_HEADER =
  "frame-ancestors 'self' chrome-extension: moz-extension:;";

// Strict CSP (default-src/script-src/connect-src/etc. directives). Off by
// default while the allowlist is validated against real deployments; enable
// with WEB_STRICT_CSP_ENABLED=true (runtime, no rebuild needed).
const strictCspEnabled =
  process.env.WEB_STRICT_CSP_ENABLED?.toLowerCase() === "true";

// Sentry has no tunnel configured, so the browser SDK POSTs events straight to
// the host embedded in the DSN. Derive that origin (build-inlined like the SDK
// itself) so connect-src covers both SaaS (*.ingest.*.sentry.io) and
// self-hosted instances; empty when Sentry is disabled or the DSN is unparseable.
const sentryConnectSrc = (() => {
  const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
  if (!dsn) return "";
  try {
    return new URL(dsn).origin;
  } catch {
    console.warn(
      "NEXT_PUBLIC_SENTRY_DSN is not a valid URL; omitting its origin from connect-src."
    );
    return "";
  }
})();

// NEXT_PUBLIC_* and NODE_ENV are inlined at build, so this stays build-time —
// only the frame-ancestors flag above is runtime.
const upgradeInsecureRequests =
  process.env.NEXT_PUBLIC_CLOUD_ENABLED === "true" &&
  process.env.NODE_ENV !== "development";

const CSP_HEADER = [
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;",
  "font-src 'self' https://fonts.gstatic.com;",
  "object-src 'none';",
  "base-uri 'self';",
  "form-action 'self';",
  frameProtectionEnabled ? FRAME_CSP_HEADER : "",
  upgradeInsecureRequests ? "upgrade-insecure-requests;" : "",
  // 'unsafe-inline' is required: the App Router emits inline scripts for
  // hydration (nonce-based CSP is a deferred follow-up). PostHog is proxied
  // same-origin via /ph_ingest (next.config.js rewrites), so 'self' covers it.
  // googletagmanager.com lets the optional GTM bootstrap (NEXT_PUBLIC_GTM_ENABLED)
  // load gtm.js; GTM-configured downstream tags may need extra origins added.
  strictCspEnabled ? "default-src 'self';" : "",
  strictCspEnabled
    ? "script-src 'self' 'unsafe-inline' https://www.googletagmanager.com;"
    : "",
  // connect-src blob: for the DOCX preview modal, which fetches the document
  // back out of a blob: URL to render it. The Sentry origin (when configured) is
  // derived from the DSN above.
  strictCspEnabled
    ? `connect-src 'self' blob:${
        sentryConnectSrc ? ` ${sentryConnectSrc}` : ""
      };`
    : "",
  // img-src stays broad: chat markdown and connector content render remote
  // images.
  strictCspEnabled ? "img-src 'self' data: blob: https:;" : "",
  // cdn.onyx.app serves the Craft page's animated background video.
  strictCspEnabled ? "media-src 'self' blob: data: https://cdn.onyx.app;" : "",
  // worker-src blob: covers pdf.js-style workers and the PostHog session
  // recorder; frame-src blob: covers in-app PDF preview.
  strictCspEnabled ? "worker-src 'self' blob:;" : "",
  strictCspEnabled ? "frame-src 'self' blob:;" : "",
]
  .filter(Boolean)
  .join(" ");

export function withSecurityHeaders(response: NextResponse): NextResponse {
  if (!response.headers.has("Content-Security-Policy")) {
    response.headers.set("Content-Security-Policy", CSP_HEADER);
  } else if (frameProtectionEnabled) {
    // Separate policies intersect; a stricter backend policy still applies.
    response.headers.append("Content-Security-Policy", FRAME_CSP_HEADER);
  }
  return response;
}
