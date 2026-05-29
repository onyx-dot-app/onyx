import type { NextConfig } from "next";

// The preview is served through the Onyx proxy at
// /api/build/sessions/<id>/webapp. When WEBAPP_ASSET_PREFIX is set (by the
// dev-server start script), emit /_next/ asset URLs already prefixed with it so
// the proxy doesn't have to rewrite them on every request.
const assetPrefix = process.env.WEBAPP_ASSET_PREFIX || undefined;

const nextConfig: NextConfig = {
  ...(assetPrefix ? { assetPrefix } : {}),
};

export default nextConfig;
