// JWT login + token lifecycle for mobile.
//
// Uses the global `fetch` directly (NOT query/client) to avoid an import cycle:
// query/client wires getAuthHeaders -> @/auth. These calls are non-streaming.
import * as WebBrowser from "expo-web-browser";
import { getApiBaseUrl } from "@/lib/serverUrl";

// Backend route consts (the backend may adjust; everything imports these names).
export const MOBILE_LOGIN_PATH = "/auth/mobile/login";
export const REGISTER_PATH = "/auth/register";
export const GOOGLE_OAUTH_AUTHORIZE_PATH = "/auth/mobile/oauth/google/authorize";
export const REFRESH_PATH = "/auth/refresh";
export const LOGOUT_PATH = "/auth/logout";

// Must match the app `scheme` ("onyx") in app.config.ts and be allowlisted on the backend.
export const AUTH_REDIRECT_URL = "onyx://callback";

const TOKEN_PARAM = "token";

export class AuthError extends Error {
  constructor(message = "Authentication failed. Please try again.") {
    super(message);
    this.name = "AuthError";
  }
}

export class InvalidCredentialsError extends AuthError {
  constructor(message = "Incorrect email or password.") {
    super(message);
    this.name = "InvalidCredentialsError";
  }
}

export class RegistrationError extends AuthError {
  constructor(message = "Could not create your account.") {
    super(message);
    this.name = "RegistrationError";
  }
}

export class SignInCancelledError extends AuthError {
  constructor(message = "Sign-in was cancelled.") {
    super(message);
    this.name = "SignInCancelledError";
  }
}

// Pull the JWT out of `onyx://callback?token=<JWT>` or the `#token=<JWT>` fragment.
// Custom-scheme URLs aren't reliably parsed by WHATWG `URL` across RN engines, so we
// extract the param manually from both query and fragment. Exported for the cold-start
// deep-link path ((auth)/callback) which never flows through openAuthSessionAsync.
export function extractTokenFromUrl(url: string): string | null {
  if (!url) return null;

  // Token may live in query or fragment, depending on how the backend issues the redirect.
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

interface BearerLoginResponse {
  access_token?: string;
  token_type?: string;
}

// Throws InvalidCredentialsError on 400/401, AuthError otherwise.
export async function loginWithPassword(email: string, password: string): Promise<string> {
  const body = new URLSearchParams();
  // fastapi-users' OAuth2PasswordRequestForm expects `username` (not `email`).
  body.append("username", email);
  body.append("password", password);

  let res: Response;
  try {
    res = await fetch(`${getApiBaseUrl()}${MOBILE_LOGIN_PATH}`, {
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

function signalsVerificationRequired(status: number, detail: string | null): boolean {
  if (status === 202) return true; // backend explicitly deferred (accepted, pending verify)
  if (!detail) return false;
  const d = detail.toLowerCase();
  return d.includes("verif"); // "verification required", "verify your email", etc.
}

export async function register(
  email: string,
  password: string,
): Promise<{ needsVerification: boolean }> {
  let res: Response;
  try {
    res = await fetch(`${getApiBaseUrl()}${REGISTER_PATH}`, {
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

// System browser (not an in-app webview) reuses the user's Google session and honors
// IdP policies (MFA, device trust). Throws SignInCancelledError on dismiss/no token.
export async function loginWithGoogle(): Promise<string> {
  // redirect=true makes the backend 302 straight to the IdP (vs returning JSON), which
  // is what openAuthSessionAsync needs; redirect_uri is the app-scheme deep link the
  // backend 302s back to with ?token=... after login.
  const authUrl =
    `${getApiBaseUrl()}${GOOGLE_OAUTH_AUTHORIZE_PATH}` +
    `?redirect_uri=${encodeURIComponent(AUTH_REDIRECT_URL)}&redirect=true`;

  const result = await WebBrowser.openAuthSessionAsync(authUrl, AUTH_REDIRECT_URL);

  if (result.type !== "success") {
    throw new SignInCancelledError();
  }

  const token = extractTokenFromUrl(result.url);
  if (!token) {
    throw new SignInCancelledError("Sign-in completed but no access token was returned.");
  }
  return token;
}

// Best-effort: JWTs are stateless, so the authoritative logout is deleting the local
// token (caller does that). Just notifies the backend if it cares. Never throws.
export async function logout(jwt: string): Promise<void> {
  if (!jwt) return;
  try {
    await fetch(`${getApiBaseUrl()}${LOGOUT_PATH}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${jwt}` },
    });
  } catch {
    // Offline / server down / route absent — ignore; local sign-out proceeds.
  }
}
