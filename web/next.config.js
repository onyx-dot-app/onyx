// Always require withSentryConfig
const { withSentryConfig } = require("@sentry/nextjs");
const { PHASE_DEVELOPMENT_SERVER } = require("next/constants");

/** @type {import('next').NextConfig} */
const nextConfig = {
  productionBrowserSourceMaps: false,
  output: "standalone",
  transpilePackages: ["@onyx-ai/opal", "@onyx-ai/shared"],
  typedRoutes: true,
  // NOTE: `reactCompiler` is set per-phase in module.exports below — enabled for
  // builds, disabled for the dev server. See the comment there for the rationale.
  // Pin the workspace root to this directory so Turbopack resolves modules
  // against web/bun.lock. Without this, Next.js detects multiple lockfiles
  // (the repo-root bun.lock and web/bun.lock) and infers the wrong root.
  turbopack: {
    root: __dirname,
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
    return [
      {
        source: "/(.*)",
        headers: [
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
              "accelerometer=(), ambient-light-sensor=(), autoplay=(), battery=(), camera=(), cross-origin-isolated=(), display-capture=(), document-domain=(), encrypted-media=(), execution-while-not-rendered=(), execution-while-out-of-viewport=(), fullscreen=(), geolocation=(), gyroscope=(), keyboard-map=(), magnetometer=(), microphone=(self), midi=(), navigation-override=(), payment=(), picture-in-picture=(), publickey-credentials-get=(), screen-wake-lock=(), sync-xhr=(), usb=(), web-share=(), xr-spatial-tracking=()",
          },
        ],
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: "/api/build/sessions/:sessionId/webapp/_next/webpack-hmr",
        destination: `${
          process.env.INTERNAL_URL || "http://localhost:8080"
        }/build/sessions/:sessionId/webapp/_next/webpack-hmr`,
      },
      {
        source: "/ph_ingest/static/:path*",
        destination: "https://us-assets.i.posthog.com/static/:path*",
      },
      {
        source: "/ph_ingest/:path*",
        destination: `${
          process.env.NEXT_PUBLIC_POSTHOG_HOST || "https://us.i.posthog.com"
        }/:path*`,
      },
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
  async redirects() {
    return [
      {
        source: "/chat",
        destination: "/app",
        permanent: true,
      },
      // NRF routes: Redirect to /nrf which doesn't require auth
      // (NRFPage handles unauthenticated users gracefully with a login modal)
      {
        source: "/app/nrf/side-panel",
        destination: "/nrf/side-panel",
        permanent: true,
      },
      {
        source: "/app/nrf",
        destination: "/nrf",
        permanent: true,
      },
      {
        source: "/chat/:path*",
        destination: "/app/:path*",
        permanent: true,
      },
      // Legacy /assistants → /agents redirects (added in PR #8869).
      // Preserves backward compatibility for bookmarks, shared links, and
      // hardcoded URLs that still reference the old /assistants paths.
      // TODO: Remove these redirects in v4.0 — https://linear.app/onyx-app/issue/ENG-3771
      {
        source: "/admin/assistants",
        destination: "/admin/agents",
        permanent: true,
      },
      {
        source: "/admin/assistants/:path*",
        destination: "/admin/agents/:path*",
        permanent: true,
      },
      {
        source: "/ee/assistants/:path*",
        destination: "/ee/agents/:path*",
        permanent: true,
      },
      {
        source: "/admin/configuration/search",
        destination: "/admin/configuration/index-settings",
        permanent: true,
      },
      {
        source: "/admin/configuration/llm",
        destination: "/admin/configuration/language-models",
        permanent: true,
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

// Export the module with conditional Sentry configuration.
//
// React Compiler is a production runtime optimization (automatic memoization). It
// provides no runtime benefit during local development, but it is expensive in the
// dev server: under Turbopack there is no native SWC path, so Next runs
// `babel-plugin-react-compiler` through a JS babel-loader that Turbopack executes
// in a pool of per-CPU-core worker subprocesses. On a many-core machine this roughly
// doubles dev-server peak memory and adds ~35-50% to route compile times.
//
// So enable it for builds (`next build`) and disable it for the dev server
// (`next dev`). Set ENABLE_REACT_COMPILER=1 to force it on locally when you want to
// validate React Compiler behavior in dev.
module.exports = (phase) => {
  const isDevServer = phase === PHASE_DEVELOPMENT_SERVER;
  return withSentryConfig(
    {
      ...nextConfig,
      reactCompiler: !isDevServer || process.env.ENABLE_REACT_COMPILER === "1",
    },
    sentryWebpackPluginOptions
  );
};
