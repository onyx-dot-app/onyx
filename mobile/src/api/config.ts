// Backend connection config.
//
// TEMPORARY: for now the base URL comes from `EXPO_PUBLIC_API_URL` (build-time
// env). In the future this will be supplied by the user at runtime — they'll
// enter their Onyx instance URL (e.g. on a connect/login screen), and this
// module will read that stored value instead of a hardcoded env var.
//
// `EXPO_PUBLIC_API_URL` is inlined by Expo into the JS bundle at build/start
// time (any `EXPO_PUBLIC_`-prefixed var is available on `process.env`). Set it
// in a gitignored `.env.local`; see `.env.example`.
//
// NOTE: `EXPO_PUBLIC_*` ships inside the client bundle — it is NOT a secret.
// Fine for a base URL; never put tokens or keys here.
//
// Resolved LAZILY (per request, inside `apiFetch`) rather than at module load:
// a throw during module evaluation can't be caught by a React error boundary
// (it crashes the bundle), whereas a throw inside the fetch surfaces as a normal
// rejected query the UI can render. This also fits the future runtime-URL model.

export function getBaseUrl(): string {
  const raw = process.env.EXPO_PUBLIC_API_URL;
  if (!raw) {
    throw new Error(
      "EXPO_PUBLIC_API_URL is not set. Copy mobile/.env.example to " +
        "mobile/.env.local and point it at the Onyx backend.",
    );
  }
  // Trim a trailing slash so callers always pass paths like "/api/me".
  return raw.replace(/\/+$/, "");
}
