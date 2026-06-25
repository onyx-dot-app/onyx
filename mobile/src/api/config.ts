// EXPO_PUBLIC_* ships in the client bundle — never put secrets here, base URL only.
// Resolved lazily per request, not at module load: a module-eval throw crashes the
// bundle uncatchably, whereas a throw here surfaces as a rejected query the UI can
// render — and per-request reads make an instance switch take effect on the next call.
import { getStoredServerUrl } from "@/state/session";

// `/api` for nginx-fronted deployments (proxy strips it); set EXPO_PUBLIC_API_PREFIX=""
// for a bare dev backend.
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
  // Host + prefix; callers pass bare paths like "/me".
  return `${raw.replace(/\/+$/, "")}${API_PREFIX}`;
}
