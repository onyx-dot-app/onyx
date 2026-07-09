// EXPO_PUBLIC_* ships in the client bundle — base URL only, never secrets.
// Resolved lazily per request so a config error is a catchable rejected query
// (not an uncatchable module-eval crash) and instance switches apply next call.
import { getStoredServerUrl } from "@/state/session";

// `/api` for nginx-fronted deployments (proxy strips it); set "" for a bare dev backend.
function normalizePrefix(raw: string): string {
  const trimmed = raw.replace(/^\/+|\/+$/g, "");
  return trimmed ? `/${trimmed}` : "";
}
const API_PREFIX = normalizePrefix(
  process.env.EXPO_PUBLIC_API_PREFIX ?? "/api",
);

export function getApiPrefix(): string {
  return API_PREFIX;
}

export function getBaseUrl(): string {
  // EXPO_PUBLIC_API_URL is the dev-only fallback.
  const raw = getStoredServerUrl() ?? process.env.EXPO_PUBLIC_API_URL;
  if (!raw) {
    throw new Error(
      "No Onyx server URL configured. Connect to an instance first " +
        "(or set EXPO_PUBLIC_API_URL in mobile/.env.local for development).",
    );
  }
  return `${raw.replace(/\/+$/, "")}${API_PREFIX}`;
}
