// Always require withSentryConfig
const { withSentryConfig } = require("@sentry/nextjs");

const cspHeader = `
    style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;
    font-src 'self' https://fonts.gstatic.com;
    object-src 'none';
    base-uri 'self';
    form-action 'self';
    ${
      process.env.NEXT_PUBLIC_CLOUD_ENABLED === "true"
        ? "upgrade-insecure-requests;"
        : ""
    }
`;

/** @type {import('next').NextConfig} */
const nextConfig = {
  productionBrowserSourceMaps: false,
  output: "standalone",
  transpilePackages: ["@onyx/opal"],
  typedRoutes: true,
  reactCompiler: true,
  compiler: {
    // Strip data-testid props in production for smaller bundles, but keep them
    // in CI/test environments (E2E_TESTING=true) so Playwright tests work
    reactRemoveProperties:
      process.env.NODE_ENV === "production" && !process.env.E2E_TESTING,
  },
  images: {
    // Used to fetch favicons
    remotePatterns: [
      {
        protocol: "https",
        hostname: "www.google.com",
        port: "",
        pathname: "/s2/favicons/**",
      },
    ],
    unoptimized: true, // Disable image optimization to avoid requiring Sharp
  },
  async headers() {
    const isDev = process.env.NODE_ENV === "development";
    return [
      {
        source: "/(.*)",
        headers: [
          {
            key: "Content-Security-Policy",
            value: cspHeader.replace(/\n/g, ""),
          },
          {
            key: "Strict-Transport-Security",
            value: "max-age=63072000; includeSubDomains; preload",
          },
          {
            key: "Referrer-Policy",
            value: "strict-origin-when-cross-origin",
          },
          {
            key: "X-Content-Type-Options",
            value: "nosniff",
          },
          {
            key: "Permissions-Policy",
            value:
              "accelerometer=(), ambient-light-sensor=(), autoplay=(), battery=(), camera=(), cross-origin-isolated=(), display-capture=(), document-domain=(), encrypted-media=(), execution-while-not-rendered=(), execution-while-out-of-viewport=(), fullscreen=(), geolocation=(), gyroscope=(), keyboard-map=(), magnetometer=(), microphone=(), midi=(), navigation-override=(), payment=(), picture-in-picture=(), publickey-credentials-get=(), screen-wake-lock=(), sync-xhr=(), usb=(), web-share=(), xr-spatial-tracking=()",
          },
        ],
      },
      {
        // Cache static assets (images, icons, fonts, etc.) to prevent refetching and re-renders
        source: "/_next/static/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: isDev
              ? "no-cache, must-revalidate" // Dev: always check if fresh
              : "public, max-age=2592000, immutable", // Prod: cache for 30 days
          },
        ],
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: "/api/docs/:path*", // catch /api/docs and /api/docs/...
        destination: `${
          process.env.INTERNAL_URL || "http://localhost:8080"
        }/docs/:path*`,
      },
      {
        source: "/api/docs", // if you also need the exact /api/docs
        destination: `${
          process.env.INTERNAL_URL || "http://localhost:8080"
        }/docs`,
      },
      {
        source: "/openapi.json",
        destination: `${
          process.env.INTERNAL_URL || "http://localhost:8080"
        }/openapi.json`,
      },
    ];
  },
};

// Sentry configuration for error monitoring:
// - Without SENTRY_AUTH_TOKEN and NEXT_PUBLIC_SENTRY_DSN: Sentry is completely disabled
// - With both configured: Capture errors and limited performance data

// Determine if Sentry should be enabled
const sentryEnabled = Boolean(
  process.env.SENTRY_AUTH_TOKEN && process.env.NEXT_PUBLIC_SENTRY_DSN
);

// Sentry webpack plugin options
const sentryWebpackPluginOptions = {
  org: process.env.SENTRY_ORG || "onyx-vl",
  project: process.env.SENTRY_PROJECT || "onyx-web",
  authToken: process.env.SENTRY_AUTH_TOKEN,
  silent: !sentryEnabled, // Silence output when Sentry is disabled
  dryRun: !sentryEnabled, // Don't upload source maps when Sentry is disabled
  ...(sentryEnabled && {
    sourceMaps: {
      include: ["./.next"],
      ignore: ["node_modules"],
      urlPrefix: "~/_next",
      stripPrefix: ["webpack://_N_E/"],
      validate: true,
      cleanArtifacts: true,
    },
  }),
};

// Export the module with conditional Sentry configuration
module.exports = withSentryConfig(nextConfig, sentryWebpackPluginOptions);
