import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // When running behind the Craft proxy, Next.js must prefix all asset URLs
  // (including the HMR WebSocket) with the session's proxy path so that
  // dynamic URL construction in client-side JS resolves through the proxy
  // rather than the domain root. Set by the sandbox manager at startup.
  assetPrefix: process.env.CRAFT_ASSET_PREFIX || undefined,
};

export default nextConfig;
