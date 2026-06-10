// Shared between next.config.js (build-time fallback headers) and
// src/proxy.ts (runtime headers). Must stay CommonJS so next.config.js can
// require() it.
//
// Why the split: headers defined in next.config.js are resolved once at
// `next build` and baked into the routes manifest, so they cannot be toggled
// at runtime. The clickjacking protection (frame-ancestors / X-Frame-Options)
// needs a runtime kill switch (DISABLE_FRAME_PROTECTION), so it is emitted
// from src/proxy.ts instead. Middleware-set headers fully REPLACE same-named
// headers from next.config.js, so proxy.ts must emit the complete CSP — this
// module is the single source of truth for the policy itself.

/**
 * Build the Content-Security-Policy header value.
 *
 * @param {string | null} frameAncestors - value for the frame-ancestors
 *   directive (e.g. "'self'"), or null to omit the directive entirely.
 * @returns {string}
 */
function buildCspHeader(frameAncestors) {
  return `
    style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;
    font-src 'self' https://fonts.gstatic.com;
    object-src 'none';
    base-uri 'self';
    form-action 'self';
    ${frameAncestors ? `frame-ancestors ${frameAncestors};` : ""}
    ${
      process.env.NEXT_PUBLIC_CLOUD_ENABLED === "true" &&
      process.env.NODE_ENV !== "development"
        ? "upgrade-insecure-requests;"
        : ""
    }
`.replace(/\n/g, "");
}

module.exports = { buildCspHeader };
