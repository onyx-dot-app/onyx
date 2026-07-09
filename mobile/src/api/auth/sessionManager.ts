import { runBrowserSso } from "@/api/auth/browserSso";
import type { ProviderDescriptor } from "@/api/auth/providers";
import { apiFetch } from "@/api/client";
import { getToken, setToken } from "@/api/auth/tokenStore";
import { isAuthError } from "@/api/errors";
import { persister, queryClient } from "@/query/client";
import { useSession } from "@/state/session";

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

// Bumped on every identity change; a late refresh applies its result only if
// unchanged, so it can't resurrect a logged-out or cross-contaminate a new session.
let sessionEpoch = 0;

// Drop in-memory + on-disk cache so a new identity can't read a prior user's data.
async function purgeCache(): Promise<void> {
  queryClient.clear();
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
  sessionEpoch += 1; // new identity → invalidate any in-flight refresh
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
    auth: false, // the code itself is the credential
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

// Register succeeded but auto-login failed (e.g. email verification required):
// account exists, so the UI must say "sign in", not "signup failed".
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

export async function clearLocalSession(): Promise<void> {
  sessionEpoch += 1; // a late refresh can't resurrect us
  await setToken(null);
  await purgeCache();
  useSession.getState().setStatus("anon");
}

export async function logout(): Promise<void> {
  // Best-effort revoke; the local wipe below runs regardless of network failure.
  try {
    await apiFetch<void>(LOGOUT_PATH, { method: "POST" });
  } catch (err) {
    console.warn("Mobile logout: server-side token revocation failed", err);
  }
  await clearLocalSession();
}

// Single-flight: concurrent callers share one in-flight refresh.
let inFlightRefresh: Promise<string | null> | null = null;

export function refreshToken(): Promise<string | null> {
  if (inFlightRefresh) return inFlightRefresh;
  const startedEpoch = sessionEpoch;
  inFlightRefresh = (async () => {
    try {
      const res = await apiFetch<BearerTokenResponse>(REFRESH_PATH, {
        method: "POST",
      });
      // Logged out/replaced mid-flight: discard rather than mix identities.
      if (sessionEpoch !== startedEpoch) return null;
      await setToken(res.access_token);
      useSession.getState().setStatus("authed");
      return res.access_token;
    } catch (err) {
      // Auth error = token rejected, unrecoverable → wipe (if same session).
      // Transient errors re-throw so the caller keeps the existing token.
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

// Test-only: clear module state so a leaked `inFlightRefresh` can't bleed into the next test.
export function __resetSessionStateForTests(): void {
  sessionEpoch = 0;
  inFlightRefresh = null;
}

// Token is opaque (not a JWT), so no client-side expiry check; return it as-is.
// Await an in-flight refresh for freshness, but fall back to the stored token on a transient throw.
export async function getValidToken(): Promise<string | null> {
  if (inFlightRefresh) {
    try {
      return await inFlightRefresh;
    } catch {
      return getToken();
    }
  }
  return getToken();
}
