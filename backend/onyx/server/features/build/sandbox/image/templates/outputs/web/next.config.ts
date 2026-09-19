import type { NextConfig } from "next";

// The cwd fallback lets a dev server the agent starts by hand still serve
// under the path the preview proxy expects.
function resolveWebappBasePath(): string | undefined {
  if (process.env.ONYX_WEBAPP_BASE_PATH) {
    return process.env.ONYX_WEBAPP_BASE_PATH;
  }
  const match = process.cwd().match(/\/sessions\/([^/]+)\/outputs\/web\/?$/);
  return match ? `/api/build/sessions/${match[1]}/webapp` : undefined;
}

const webappBasePath = resolveWebappBasePath();
const allowedDevOrigins = (process.env.ONYX_WEBAPP_ALLOWED_DEV_ORIGINS || "")
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean);

const nextConfig: NextConfig = {};

if (webappBasePath) {
  nextConfig.basePath = webappBasePath;
  nextConfig.assetPrefix = webappBasePath;
  // Point naive probes of "/" (which otherwise 404) at the real app.
  nextConfig.redirects = async () => [
    {
      source: "/",
      destination: webappBasePath,
      basePath: false,
      permanent: false,
    },
  ];
}

if (allowedDevOrigins.length > 0) {
  nextConfig.allowedDevOrigins = allowedDevOrigins;
}

export default nextConfig;
