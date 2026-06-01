// JWT login + token lifecycle for mobile.
//
// Three ways in, all yielding a JWT bearer token the app stores and sends as
// `Authorization: Bearer <jwt>`:
//
//   1. Email/password — POST form-urlencoded credentials to the backend's mobile
//      Bearer-transport login route; the backend validates and returns a JWT.
//   2. Google OAuth — open the backend's Google authorize URL in the *system
//      browser* via expo-web-browser. Using the system browser (not an in-app
//      webview) reuses the user's existing Google session and honors IdP policies
//      (MFA, device trust). The backend runs the OAuth dance, mints a JWT, and
//      302-redirects back to the app's deep-link scheme `onyx://callback` with the
//      JWT in the URL. We extract it and hand it back to the caller.
//   3. In-app registration — POST JSON credentials to the backend register route;
//      the backend may require email verification before the account can log in.
//
// This module deliberately uses the global `fetch` directly (NOT query/client) to
// avoid an import cycle: query/client wires getAuthHeaders -> @/auth, so importing
// it back here would be circular. These auth calls are non-streaming, so the
// global fetch is sufficient.
//
// The exact backend paths are placeholders the backend may adjust — see the named
// path consts below.
import * as WebBrowser from "expo-web-browser";
import { appConfig } from "@/lib/config";

// ── Backend route consts (the backend may adjust; everything imports these names) ─────

/** fastapi-users BearerTransport login. Form-urlencoded `username`+`password` -> JWT. */
export const MOBILE_LOGIN_PATH = "/auth/mobile/login";

/** fastapi-users register. JSON `{ email, password }` -> 201 UserRead (may need verify). */
export const REGISTER_PATH = "/auth/register";

/** Kicks off Google OAuth on the backend, which mints a JWT and 302s to the redirect. */
export const GOOGLE_OAUTH_AUTHORIZE_PATH = "/auth/mobile/oauth/google/authorize";

/** Best-effort token refresh. May not exist / may need a cookie; treat as optional. */
export const REFRESH_PATH = "/auth/refresh";

/** Best-effort server-side logout. JWT is stateless, so this is optional. */
export const LOGOUT_PATH = "/auth/logout";

/**
 * Deep-link the backend 302-redirects to after a successful OAuth login. Must match
 * the app `scheme` ("onyx") in app.config.ts and be allowlisted on the backend.
 */
export const AUTH_REDIRECT_URL = "onyx://callback";

/** Query/fragment param the backend uses to carry the minted JWT in the redirect. */
const TOKEN_PARAM = "token";

// ── Error classes (typed so screens can branch on them) ──────────────────────────

/** Generic auth failure (network error, unexpected status, malformed response). */
export class AuthError extends Error {
  constructor(message = "Authentication failed. Please try again.") {
    super(message);
    this.name = "AuthError";
  }
}

/** Email/password login rejected (400/401) — wrong email or password. */
export class InvalidCredentialsError extends AuthError {
  constructor(message = "Incorrect email or password.") {
    super(message);
    this.name = "InvalidCredentialsError";
  }
}

/** Registration failed with a readable, user-facing reason (e.g. user exists). */
export class RegistrationError extends AuthError {
  constructor(message = "Could not create your account.") {
    super(message);
    this.name = "RegistrationError";
  }
}

/** The user dismissed/cancelled the OAuth browser, or no token came back. */
export class SignInCancelledError extends AuthError {
  constructor(message = "Sign-in was cancelled.") {
    super(message);
    this.name = "SignInCancelledError";
  }
}

// ── Token redirect parsing ───────────────────────────────────────────────────────

/**
 * Pull the JWT out of a redirect URL like `onyx://callback?token=<JWT>` or the
 * fragment variant `onyx://callback#token=<JWT>`. Returns `null` if the URL carries
 * no token (an error redirect or an unrelated deep link).
 *
 * Exported because the cold-start deep-link path (the (auth)/callback route) needs
 * to parse a launch URL that never flowed through openAuthSessionAsync.
 *
 * Implementation note: custom-scheme URLs (`onyx://…`) are not reliably parsed by
 * the WHATWG `URL` class across RN engines, so we extract the param manually from
 * both the query and the fragment.
 */
export function extractTokenFromUrl(url: string): string | null {
  if (!url) return null;

  // Collect the raw query (?...) and fragment (#...) bodies regardless of order;
  // the token may live in either, depending on how the backend issues the redirect.
  const candidates: string[] = [];
  const queryIdx = url.indexOf("?");
  const fragmentIdx = url.indexOf("#");
  if (queryIdx !== -1) {
    const end = fragmentIdx !== -1 && fragmentIdx > queryIdx ? fragmentIdx : url.length;
    candidates.push(url.slice(queryIdx + 1, end));
  }
  if (fragmentIdx !== -1) {
    const end = queryIdx !== -1 && queryIdx > fragmentIdx ? queryIdx : url.length;
    candidates.push(url.slice(fragmentIdx + 1, end));
  }

  for (const raw of candidates) {
    const params = new URLSearchParams(raw);
    const token = params.get(TOKEN_PARAM);
    if (token) return token.trim();
  }
  return null;
}

// ── Email / password login ────────────────────────────────────────────────────────

interface BearerLoginResponse {
  access_token?: string;
  token_type?: string;
}

/**
 * Log in with email + password. POSTs form-urlencoded `username`/`password` to the
 * backend's mobile Bearer-transport login route (fastapi-users `OAuth2PasswordRequestForm`
 * shape) and returns the JWT `access_token`.
 *
 * Throws InvalidCredentialsError on 400/401 (bad credentials), AuthError otherwise.
 */
export async function loginWithPassword(email: string, password: string): Promise<string> {
  const body = new URLSearchParams();
  // fastapi-users' OAuth2PasswordRequestForm expects `username` (not `email`).
  body.append("username", email);
  body.append("password", password);

  let res: Response;
  try {
    res = await fetch(`${appConfig.apiBaseUrl}${MOBILE_LOGIN_PATH}`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });
  } catch {
    throw new AuthError("Couldn't reach the server. Check your connection and try again.");
  }

  if (res.status === 400 || res.status === 401) {
    throw new InvalidCredentialsError();
  }
  if (!res.ok) {
    throw new AuthError();
  }

  let data: BearerLoginResponse;
  try {
    data = (await res.json()) as BearerLoginResponse;
  } catch {
    throw new AuthError();
  }
  if (!data.access_token) {
    throw new AuthError();
  }
  return data.access_token;
}

// ── Registration ───────────────────────────────────────────────────────────────────

/** Best-effort extraction of a readable error message from a fastapi-users error body. */
async function readErrorDetail(res: Response): Promise<string | null> {
  try {
    const data = (await res.json()) as { detail?: unknown };
    const detail = data?.detail;
    if (typeof detail === "string") return detail;
    // fastapi-users can return a structured detail (e.g. { code, reason }).
    if (detail && typeof detail === "object") {
      const reason = (detail as { reason?: unknown }).reason;
      if (typeof reason === "string") return reason;
    }
  } catch {
    // Non-JSON body — fall through to null.
  }
  return null;
}

/** Heuristic: does this register response/detail mean "verify your email first"? */
function signalsVerificationRequired(status: number, detail: string | null): boolean {
  if (status === 202) return true; // backend explicitly deferred (accepted, pending verify)
  if (!detail) return false;
  const d = detail.toLowerCase();
  return d.includes("verif"); // "verification required", "verify your email", etc.
}

/**
 * Register a new account. POSTs JSON `{ email, password }` to the backend register
 * route.
 *
 *  - 2xx success -> resolves. If the backend signals that email verification is
 *    required before login, resolves with `{ needsVerification: true }`.
 *  - 400 (e.g. user already exists / weak password) -> throws RegistrationError
 *    with a readable message.
 *  - other non-2xx / network error -> throws AuthError.
 */
export async function register(
  email: string,
  password: string,
): Promise<{ needsVerification: boolean }> {
  let res: Response;
  try {
    res = await fetch(`${appConfig.apiBaseUrl}${REGISTER_PATH}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
  } catch {
    throw new AuthError("Couldn't reach the server. Check your connection and try again.");
  }

  if (res.ok || res.status === 202) {
    const detail = res.status === 202 ? await readErrorDetail(res) : null;
    return { needsVerification: signalsVerificationRequired(res.status, detail) };
  }

  if (res.status === 400) {
    const detail = await readErrorDetail(res);
    // A 400 can still be the "verify your email" path on some backends.
    if (signalsVerificationRequired(res.status, detail)) {
      return { needsVerification: true };
    }
    throw new RegistrationError(detail ?? "Could not create your account.");
  }

  throw new AuthError();
}

// ── Google OAuth ────────────────────────────────────────────────────────────────────

/**
 * Open the system browser to the backend's Google authorize URL and resolve with the
 * minted JWT once the backend redirects to `onyx://callback?token=...` (or `#token=`).
 *
 * Throws SignInCancelledError if the user dismisses the browser, the OS cancels the
 * session, or the redirect carries no token.
 */
export async function loginWithGoogle(): Promise<string> {
  const authUrl =
    `${appConfig.apiBaseUrl}${GOOGLE_OAUTH_AUTHORIZE_PATH}` +
    `?redirect_uri=${encodeURIComponent(AUTH_REDIRECT_URL)}`;

  // openAuthSessionAsync watches for a redirect to AUTH_REDIRECT_URL and resolves
  // with `{ type: "success", url }` when it sees one; "cancel"/"dismiss" otherwise.
  const result = await WebBrowser.openAuthSessionAsync(authUrl, AUTH_REDIRECT_URL);

  if (result.type !== "success") {
    // "cancel" (user backed out), "dismiss" (OS closed it), or "locked".
    throw new SignInCancelledError();
  }

  const token = extractTokenFromUrl(result.url);
  if (!token) {
    throw new SignInCancelledError("Sign-in completed but no access token was returned.");
  }
  return token;
}

// ── Logout ───────────────────────────────────────────────────────────────────────────

/**
 * Best-effort server-side logout. JWTs are stateless, so the authoritative logout is
 * deleting the local token (the caller does that). This just notifies the backend if
 * it cares (e.g. to clear a server-side session/cookie). Never throws.
 */
export async function logout(jwt: string): Promise<void> {
  if (!jwt) return;
  try {
    await fetch(`${appConfig.apiBaseUrl}${LOGOUT_PATH}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${jwt}` },
    });
  } catch {
    // Offline / server down / route absent — ignore; local sign-out proceeds.
  }
}
