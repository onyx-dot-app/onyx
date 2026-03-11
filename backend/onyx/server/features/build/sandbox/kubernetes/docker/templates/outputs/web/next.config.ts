import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Routes all asset URLs (including HMR WebSocket) through the Craft proxy path.
  assetPrefix: process.env.CRAFT_ASSET_PREFIX || undefined,
};

export default nextConfig;
