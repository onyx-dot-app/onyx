const NEXT_PUBLIC_ONYX_BACKEND_URL =
  process.env.NEXT_PUBLIC_ONYX_BACKEND_URL;

const DEV_FRONTEND_PORT = "3000";
const DEFAULT_DEV_BACKEND_PORT = "8080";

interface BrowserWebSocketUrlOptions {
  directPath: string;
  proxiedPath: string;
  token: string;
  devBackendPort?: string;
}

function getConfiguredPublicBackendUrl(): URL | null {
  if (!NEXT_PUBLIC_ONYX_BACKEND_URL) {
    return null;
  }

  try {
    return new URL(NEXT_PUBLIC_ONYX_BACKEND_URL);
  } catch {
    console.warn(
      "Ignoring invalid NEXT_PUBLIC_ONYX_BACKEND_URL:",
      NEXT_PUBLIC_ONYX_BACKEND_URL
    );
    return null;
  }
}

export function buildBrowserWebSocketUrl({
  directPath,
  proxiedPath,
  token,
  devBackendPort = DEFAULT_DEV_BACKEND_PORT,
}: BrowserWebSocketUrlOptions): string {
  const configuredBackendUrl = getConfiguredPublicBackendUrl();
  if (configuredBackendUrl) {
    const protocol =
      configuredBackendUrl.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${configuredBackendUrl.host}${proxiedPath}?token=${encodeURIComponent(token)}`;
  }

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const isDev = window.location.port === DEV_FRONTEND_PORT;
  const host = isDev ? `localhost:${devBackendPort}` : window.location.host;
  const path = isDev ? directPath : proxiedPath;

  return `${protocol}//${host}${path}?token=${encodeURIComponent(token)}`;
}
