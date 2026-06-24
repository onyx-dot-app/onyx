// Single orchestration point for the mobile session lifecycle; all session
// mutations route through here so the token-and-cache invariants live in one place.
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

// V1 supports only email/password; PR5 widens this union with a `browser` SSO variant.
export type LoginMethod = {
  kind: "password";
  email: string;
  password: string;
};

const LOGIN_PATH = "/auth/mobile/login";
const REFRESH_PATH = "/auth/mobile/refresh";
const LOGOUT_PATH = "/auth/mobile/logout";
// Shared (non-mobile) fastapi-users route; only creates the user.
const REGISTER_PATH = "/auth/register";

// Bumped on every identity change; an in-flight refresh applies its result only
// if this is unchanged, so a refresh resolving after logout/re-login can't
// resurrect a cleared session or cross-contaminate a new one. (Single-flight
// dedupes concurrent refreshes; it does nothing to order them against login/logout.)
let sessionEpoch = 0;

// Drop in-memory + on-disk query cache on both login and logout so a new
// identity can never read a previous user's cached data.
async function purgeCache(): Promise<void> {
  queryClient.clear();
  await persister.removeClient();
}

// fastapi-users `/login` expects an OAuth2 password form (`username`/`password`), not JSON.
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
  // Install the new token before purging so a query firing mid-purge reads the
  // new identity's token, not the prior user's (which would repopulate the cache).
  await setToken(res.access_token);
  await purgeCache();
  useSession.getState().setStatus("authed");
}

// register() succeeded but the follow-up auto-login failed (e.g. the instance requires email
// verification): the account exists, so the UI must say "sign in", not "signup failed".
export class PostRegisterLoginError extends Error {
  readonly loginError: unknown;
  constructor(loginError: unknown) {
    super("Account created but automatic sign-in failed");
    this.name = "PostRegisterLoginError";
    this.loginError = loginError;
  }
}

// Create the account, then log in to mint the bearer (register issues no token).
export async function register(params: {
  email: string;
  password: string;
}): Promise<void> {
  await apiFetch<unknown>(REGISTER_PATH, {
    method: "POST",
    auth: false,
    body: { email: params.email, password: params.password },
  });
  try {
    await login({
      kind: "password",
      email: params.email,
      password: params.password,
    });
  } catch (loginError) {
    throw new PostRegisterLoginError(loginError);
  }
}

// Wipe the session locally; used by logout and on an irrecoverable refresh failure.
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
      // Session logged out/replaced mid-flight: discard rather than mix identities.
      if (sessionEpoch !== startedEpoch) return null;
      await setToken(res.access_token);
      useSession.getState().setStatus("authed");
      return res.access_token;
    } catch (err) {
      // Auth error = token already rejected (revoked/expired), unrecoverable: drop
      // to logged-out, but only if still the same session. Transient errors re-throw
      // so the caller keeps the existing token and can retry later.
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

// Test-only: reset module-level state so a leaked `inFlightRefresh` can't make
// the next test's `refreshToken()` silently reuse a stale promise.
export function __resetSessionStateForTests(): void {
  sessionEpoch = 0;
  inFlightRefresh = null;
}

// The V1 token is opaque (not a JWT), so expiry can't be read client-side; this
// returns the stored token as-is without pre-emptive refresh. If a refresh is
// in flight, callers await it for the freshest token — but a transient failure
// must not deny them the still-valid stored token, so fall back to it on throw.
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
