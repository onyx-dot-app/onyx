import type { NextConfig } from "next";

const webappBasePath = process.env.ONYX_WEBAPP_BASE_PATH || undefined;

const nextConfig: NextConfig = {
  ...(webappBasePath
    ? { basePath: webappBasePath, assetPrefix: webappBasePath }
    : {}),
};

export default nextConfig;
