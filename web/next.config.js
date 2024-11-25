// Get Danswer Web Version
const { version: package_version } = require("./package.json"); // version from package.json
const env_version = process.env.DANSWER_VERSION; // version from env variable
// Use env version if set & valid, otherwise default to package version
const version = env_version || package_version;

// Always require withSentryConfig
const { withSentryConfig } = require("@sentry/nextjs");

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  publicRuntimeConfig: {
    version,
  },
};

// Sentry configuration for error monitoring:
// - Without SENTRY_AUTH_TOKEN and NEXT_PUBLIC_SENTRY_DSN: Sentry is completely disabled
// - With both configured: Only unhandled errors are captured (no performance/session tracking)

// Determine if Sentry should be enabled
const sentryEnabled = Boolean(
  process.env.SENTRY_AUTH_TOKEN && process.env.NEXT_PUBLIC_SENTRY_DSN
);

// Sentry webpack plugin options
const sentryWebpackPluginOptions = {
  org: process.env.SENTRY_ORG || "danswer",
  project: process.env.SENTRY_PROJECT || "data-plane-web",
  authToken: process.env.SENTRY_AUTH_TOKEN,
  silent: !sentryEnabled, // Silence output when Sentry is disabled
  dryRun: !sentryEnabled, // Don't upload source maps when Sentry is disabled
  sourceMaps: {
    include: ["./.next"],
    validate: false,
    urlPrefix: "~/_next",
    skip: !sentryEnabled,
  },
};

// Export the module with conditional Sentry configuration
module.exports = withSentryConfig(nextConfig, sentryWebpackPluginOptions);
