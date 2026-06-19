// SessionManager — the single orchestration point for the mobile session
// lifecycle: acquiring the Bearer token (login), revoking it (logout), keeping
// it fresh (refresh — single-flight), and reading the current valid token.
//
// It composes the lower-level seams: `apiFetch` (HTTP), `tokenStore` (keychain),
// the TanStack query cache + MMKV persister (PII purge), and `useSession`
// (coarse status). All session mutations go through here so the
// token-and-cache invariants live in one place. Endpoints come from the mobile
// bearer gateway shipped in PR1 (`backend/onyx/server/auth/mobile.py`).
import { apiFetch } from "@/api/client";
import { getToken, setToken } from "@/api/auth/tokenStore";
import { isAuthError } from "@/api/errors";
import { persister, queryClient } from "@/query/client";
import { useSession } from "@/state/session";

// fastapi-users BearerTransport login/refresh response shape.
export interface BearerTokenResponse {
  access_token: string;
  token_type: string;
}

// V1 supports only email/password. PR5 widens this union with a `browser`
// variant routed through `runBrowserSso` (system-browser PKCE flow).
export type LoginMethod = {
  kind: "password";
  email: string;
  password: string;
};

const LOGIN_PATH = "/api/auth/mobile/login";
const REFRESH_PATH = "/api/auth/mobile/refresh";
const LOGOUT_PATH = "/api/auth/mobile/logout";

// Monotonic session generation, bumped whenever the identity changes (login or
// a local clear). An in-flight refresh captures this when it starts and only
// applies its result if it's unchanged — so a refresh that resolves *after* a
// logout / re-login can't resurrect a cleared session or cross-contaminate a
// new one. (The single-flight guard below only dedupes concurrent refreshes; it
// does nothing to order a refresh against login/logout — that's what this is for.)
let sessionEpoch = 0;

// Drop every trace of the in-memory + on-disk query cache. Done on both login
// and logout so a new identity can never read a previous user's cached data
// (e.g. if the prior session ended by token expiry rather than explicit logout).
async function purgeCache(): Promise<void> {
  queryClient.clear();
  await persister.removeClient();
}

// fastapi-users `/login` expects an OAuth2 password form (`username`/`password`),
// not JSON. URLSearchParams is sent as-is by `apiFetch` with the correct
// `application/x-www-form-urlencoded` content type.
function passwordForm(email: string, password: string): URLSearchParams {
  const form = new URLSearchParams();
  form.set("username", email);
  form.set("password", password);
  return form;
}

export async function login(method: LoginMethod): Promise<void> {
  const res = await apiFetch<BearerTokenResponse>(LOGIN_PATH, {
    method: "POST",
    auth: false, // no token yet
    body: passwordForm(method.email, method.password),
  });
  sessionEpoch += 1; // new identity → invalidate any in-flight refresh
  // Install the new token BEFORE purging so any query that fires during the
  // purge reads the *new* identity's token, never the prior user's (which would
  // repopulate the just-cleared cache with the wrong identity's data).
  await setToken(res.access_token);
  await purgeCache();
  useSession.getState().setStatus("authed");
}

// Wipe the session locally: keychain token, in-memory cache, persisted snapshot,
// and status. Used by logout and on an irrecoverable refresh failure.
export async function clearLocalSession(): Promise<void> {
  sessionEpoch += 1; // invalidate any in-flight refresh so it can't resurrect us
  await setToken(null);
  await purgeCache();
  useSession.getState().setStatus("anon");
}

export async function logout(): Promise<void> {
  // Best-effort server-side revocation; the local wipe runs regardless so a
  // network failure can't strand the user half-logged-out.
  try {
    await apiFetch<void>(LOGOUT_PATH, { method: "POST" });
  } catch (err) {
    // Log so a failed revocation stays traceable, then fall through to the
    // local wipe — the on-device token is cleared regardless of the outcome.
    console.warn("Mobile logout: server-side token revocation failed", err);
  }
  await clearLocalSession();
}

// Single-flight refresh: concurrent callers share one in-flight request, so a
// burst of near-simultaneous triggers can't fan out into N refresh calls.
let inFlightRefresh: Promise<string | null> | null = null;

export function refreshToken(): Promise<string | null> {
  if (inFlightRefresh) return inFlightRefresh;
  const startedEpoch = sessionEpoch;
  inFlightRefresh = (async () => {
    try {
      const res = await apiFetch<BearerTokenResponse>(REFRESH_PATH, {
        method: "POST",
      });
      // If the session was logged out / replaced while this was in flight,
      // discard the refreshed token rather than resurrect or mix identities.
      if (sessionEpoch !== startedEpoch) return null;
      await setToken(res.access_token);
      useSession.getState().setStatus("authed");
      return res.access_token;
    } catch (err) {
      // An auth error means the server already rejected our token
      // (revoked/expired) — it's unrecoverable, so drop to a clean logged-out
      // state, but only if this is still the same session (don't clobber one
      // that already moved on). Transient/network errors are re-thrown so the
      // caller keeps the existing token and can retry later.
      if (isAuthError(err)) {
        if (sessionEpoch === startedEpoch) await clearLocalSession();
        return null;
      }
      throw err;
    } finally {
      inFlightRefresh = null;
    }
  })();
  return inFlightRefresh;
}

// Test-only: reset the module-level session state (epoch + single-flight
// handle) so each test starts from a known-clean slate. Without this, a test
// that leaves `inFlightRefresh` non-null would make the next test's
// `refreshToken()` silently reuse the stale promise. No production callers.
export function __resetSessionStateForTests(): void {
  sessionEpoch = 0;
  inFlightRefresh = null;
}

// Returns a usable Bearer token, or null if none. The V1 session token is an
// opaque, server-revocable value (not a JWT), so its expiry can't be read
// client-side; getValidToken therefore returns the stored token as-is and does
// not pre-emptively refresh. If a refresh is already in flight, callers await it
// so everyone ends up with the freshest token (single-flight) — but a *transient*
// refresh failure must not deny them the still-valid stored token, so we fall
// back to it on a thrown error. Proactive foreground / pre-expiry refresh is
// driven externally via `refreshToken` (wired to the AppState focus bridge in a
// later PR).
export async function getValidToken(): Promise<string | null> {
  if (inFlightRefresh) {
    try {
      return await inFlightRefresh;
    } catch {
      // Transient refresh failure (auth failures resolve to null, not throw).
      return getToken();
    }
  }
  return getToken();
}
