// Single source of truth for the CSP, shared by next.config.js (build-time
// fallback) and src/proxy.ts (runtime). Must stay CommonJS for the require()
// in next.config.js. Proxy-set headers fully REPLACE same-named config
// headers, so the proxy must emit the complete CSP — never a partial one.

/**
 * @param {string | null} frameAncestors - frame-ancestors directive value
 *   (e.g. "'self'"), or null to omit the directive.
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
