import { runBrowserSso } from "@/api/auth/browserSso";
import type { ProviderDescriptor } from "@/api/auth/providers";
import { apiFetch } from "@/api/client";
import {
  getInFlightRefresh,
  setInFlightRefresh,
} from "@/api/auth/refreshState";
import { setToken } from "@/api/auth/tokenStore";
import { isAuthError } from "@/api/errors";
import { toast } from "@/hooks/useToast";
import { persister, queryClient } from "@/query/client";
import { getStoredServerUrl, useSession } from "@/state/session";
import { useUserFileStore } from "@/state/userFileStore";

export interface BearerTokenResponse {
  access_token: string;
  token_type: string;
}

export type LoginMethod =
  | { kind: "password"; email: string; password: string }
  | { kind: "browser"; provider: ProviderDescriptor };

const LOGIN_PATH = "/auth/mobile/login";
const REFRESH_PATH = "/auth/mobile/refresh";
const LOGOUT_PATH = "/auth/mobile/logout";
const SSO_EXCHANGE_PATH = "/auth/mobile/sso/exchange";
// Shared (non-mobile) route; only creates the user, mints no token.
const REGISTER_PATH = "/auth/register";

// Bumped on every identity change; a late refresh applies its result only if unchanged, so it can't resurrect a logged-out session.
let sessionEpoch = 0;

/*
 * The epoch alone can't see an instance switch: the connect screen swaps the stored server URL
 * without touching it, while `setToken` derives its keychain key from whatever URL is current when
 * it writes. A refresh that outlived the switch would file the old instance's bearer under the new
 * one's key, and every later request would hand that bearer to a different server.
 */
function sameSession(epoch: number, serverUrl: string | null): boolean {
  return sessionEpoch === epoch && getStoredServerUrl() === serverUrl;
}

// userFileStore keeps file records outside the Query cache, so clearing that cache alone would leak the prior user's data.
async function purgeCache(): Promise<void> {
  queryClient.clear();
  useUserFileStore.getState().reset();
  toast.clearAll();
  await persister.removeClient();
}

// `/login` expects an OAuth2 password form (`username`/`password`), not JSON.
function passwordForm(email: string, password: string): URLSearchParams {
  const form = new URLSearchParams();
  form.set("username", email);
  form.set("password", password);
  return form;
}

async function installSession(accessToken: string): Promise<void> {
  sessionEpoch += 1;
  // Install the new token before purging, else a query firing mid-purge repopulates the cache with the prior user's data.
  await setToken(accessToken);
  await purgeCache();
  useSession.getState().setStatus("authed");
}

async function passwordLogin(email: string, password: string): Promise<string> {
  const res = await apiFetch<BearerTokenResponse>(LOGIN_PATH, {
    method: "POST",
    auth: false,
    body: passwordForm(email, password),
  });
  return res.access_token;
}

// Verifier rides only this TLS exchange, never the deep link.
async function browserLogin(provider: ProviderDescriptor): Promise<string> {
  const { code, codeVerifier } = await runBrowserSso(provider);
  const res = await apiFetch<BearerTokenResponse>(SSO_EXCHANGE_PATH, {
    method: "POST",
    auth: false,
    body: { code, code_verifier: codeVerifier },
  });
  return res.access_token;
}

export async function login(method: LoginMethod): Promise<void> {
  const accessToken =
    method.kind === "password"
      ? await passwordLogin(method.email, method.password)
      : await browserLogin(method.provider);
  await installSession(accessToken);
}

// The account exists (auto-login failed, e.g. email verification required), so the UI must say "sign in", not "signup failed".
export class PostRegisterLoginError extends Error {
  readonly loginError: unknown;
  constructor(loginError: unknown) {
    super("Account created but automatic sign-in failed");
    this.name = "PostRegisterLoginError";
    this.loginError = loginError;
  }
}

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

export async function clearLocalSession(): Promise<void> {
  sessionEpoch += 1;
  await setToken(null);
  await purgeCache();
  useSession.getState().setStatus("anon");
}

export async function logout(): Promise<void> {
  try {
    await apiFetch<void>(LOGOUT_PATH, { method: "POST" });
  } catch (err) {
    console.warn("Mobile logout: server-side token revocation failed", err);
  }
  await clearLocalSession();
}

export function refreshToken(): Promise<string | null> {
  const pending = getInFlightRefresh();
  if (pending) return pending;
  const startedEpoch = sessionEpoch;
  const startedServerUrl = getStoredServerUrl();
  const refresh = (async () => {
    try {
      const res = await apiFetch<BearerTokenResponse>(REFRESH_PATH, {
        method: "POST",
        // This request *is* the in-flight refresh, so asking for a "valid" token would await its own promise.
        auth: "stored",
      });
      /*
       * Logged out, replaced, or pointed at another instance mid-flight: discard rather than mix
       * identities.
       */
      if (!sameSession(startedEpoch, startedServerUrl)) return null;
      await setToken(res.access_token);
      useSession.getState().setStatus("authed");
      return res.access_token;
    } catch (err) {
      // Only an auth error means the token is dead; a transient one re-throws so the caller keeps it.
      if (isAuthError(err)) {
        // Same reasoning: clearing here after a switch would wipe the new instance's session.
        if (sameSession(startedEpoch, startedServerUrl)) {
          try {
            await clearLocalSession();
          } catch (clearError) {
            /*
             * A throw in here escapes the enclosing catch, so it would reach the fire-and-forget
             * caller as an unlogged rejection with the session half-cleared. The token is dead
             * either way, so report it and still answer null.
             */
            console.warn("Mobile session clear failed", clearError);
          }
        }
        return null;
      }
      /*
       * Both callers swallow this — the refresh loop drops it, and `getValidToken` falls back to
       * the stored token — so without a line here a session that dies from repeated failed
       * refreshes leaves no trace. Logged at the attempt, not at the call sites: one line per
       * refresh however many requests were waiting on it.
       */
      console.warn("Mobile token refresh failed", err);
      throw err;
    } finally {
      setInFlightRefresh(null);
    }
  })();
  // Safe after the call: the IIFE can only reach its `finally` on a later microtask.
  setInFlightRefresh(refresh);
  return refresh;
}

export function __resetSessionStateForTests(): void {
  sessionEpoch = 0;
  setInFlightRefresh(null);
}

export { getValidToken } from "@/api/auth/refreshState";
