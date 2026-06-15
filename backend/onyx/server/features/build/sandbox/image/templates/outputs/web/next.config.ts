import type { NextConfig } from "next";

const webappBasePath = process.env.ONYX_WEBAPP_BASE_PATH || undefined;

const nextConfig: NextConfig = {};

if (webappBasePath) {
  nextConfig.basePath = webappBasePath;
  nextConfig.assetPrefix = webappBasePath;
}

export default nextConfig;
