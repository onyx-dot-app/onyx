// Backend connection config.
//
// The base URL is the user-entered Onyx instance URL (cloud or self-hosted),
// captured on the connect screen and persisted via `state/session.ts`. For
// development, `EXPO_PUBLIC_API_URL` is a fallback used only when nothing has
// been stored yet — Expo inlines any `EXPO_PUBLIC_`-prefixed var into the JS
// bundle at build/start time (set it in a gitignored `.env.local`; see
// `.env.example`).
//
// NOTE: `EXPO_PUBLIC_*` ships inside the client bundle — it is NOT a secret.
// Fine for a base URL; never put tokens or keys here.
//
// Resolved LAZILY (per request, inside `apiFetch`) rather than at module load:
// a throw during module evaluation can't be caught by a React error boundary
// (it crashes the bundle), whereas a throw inside the fetch surfaces as a normal
// rejected query the UI can render. Reading the stored URL per request also
// means an instance switch takes effect on the very next call.
import { getStoredServerUrl } from "@/state/session";

export function getBaseUrl(): string {
  // Runtime server URL wins; EXPO_PUBLIC_API_URL is the dev-only fallback.
  const raw = getStoredServerUrl() ?? process.env.EXPO_PUBLIC_API_URL;
  if (!raw) {
    throw new Error(
      "No Onyx server URL configured. Connect to an instance first " +
        "(or set EXPO_PUBLIC_API_URL in mobile/.env.local for development).",
    );
  }
  // Trim a trailing slash so callers always pass paths like "/api/me".
  return raw.replace(/\/+$/, "");
}
