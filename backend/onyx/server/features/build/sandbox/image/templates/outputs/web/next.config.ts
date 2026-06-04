import type { NextConfig } from "next";

// When set by the dev-server start script, emits pre-proxied /_next/ URLs.
const assetPrefix = process.env.WEBAPP_ASSET_PREFIX || undefined;

const nextConfig: NextConfig = {
  ...(assetPrefix ? { assetPrefix } : {}),
};

export default nextConfig;
