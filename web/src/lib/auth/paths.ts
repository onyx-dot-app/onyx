import { validateInternalRedirect } from "@/lib/auth/utils";

/** Prefix for unauthenticated routes (login, signup, password reset, etc.). */
export const AUTH_PATH_PREFIX = "/auth";

export const LOGIN_PATH = "/auth/login";

export const SIGNUP_PATH = "/auth/signup";

export const AUTH_ERROR_PATH = "/auth/error";

/** The page an emailed sign-in link opens. The backend builds the same path. */
export const MAGIC_LINK_PATH = "/auth/magic-link";

/** Playground: the person chose to start a new team on /auth/error. */
export const START_NEW_TEAM_PARAM = "start_new_team";

/** Stamped by the proxy with the request path and query, since layouts
 * cannot read the URL; requireAuth() hands it back as the login `next`. */
export const ORIGINAL_PATH_HEADER = "x-onyx-original-path";

/** Login page flag. `false` keeps the SSO button instead of auto-starting it. */
export const SSO_AUTO_REDIRECT_PARAM = "autoRedirectToSso";

/** Narrow enough for Next's typed routes without a cast. */
type LoginPath = typeof LOGIN_PATH | `${typeof LOGIN_PATH}?${string}`;

interface LoginPathOptions {
  /** Where to land after login. Dropped unless it is an internal path. */
  next?: string | null;
  autoRedirectToSso?: boolean;
}

export function loginPath({
  next,
  autoRedirectToSso,
}: LoginPathOptions = {}): LoginPath {
  const params = new URLSearchParams();
  const validatedNext = validateInternalRedirect(next);
  if (validatedNext) params.set("next", validatedNext);
  if (autoRedirectToSso === false) {
    params.set(SSO_AUTO_REDIRECT_PARAM, "false");
  }
  const query = params.toString();
  return query ? `${LOGIN_PATH}?${query}` : LOGIN_PATH;
}

type SignupPath = typeof SIGNUP_PATH | `${typeof SIGNUP_PATH}?${string}`;

export function signupPath({
  startNewTeam = false,
}: { startNewTeam?: boolean } = {}): SignupPath {
  return startNewTeam
    ? `${SIGNUP_PATH}?${START_NEW_TEAM_PARAM}=true`
    : SIGNUP_PATH;
}

type AuthErrorPath =
  | typeof AUTH_ERROR_PATH
  | `${typeof AUTH_ERROR_PATH}?${string}`;

/** The error page, showing `error` (a known code or a sentence) if given. */
export function authErrorPath(error?: string | null): AuthErrorPath {
  if (!error) return AUTH_ERROR_PATH;
  return `${AUTH_ERROR_PATH}?${new URLSearchParams({ error }).toString()}`;
}

/**
 * True when `pathname` is an unauthenticated `/auth/*` route.
 *
 * Used to gate global app-shell fetches that fire from the root layout: the
 * providers/banners mounted there run on every route, including the login page,
 * where an unauthenticated caller would otherwise trigger expected-but-noisy
 * 403s (e.g. `/api/settings`, `/api/llm/provider`, `/api/notifications`).
 *
 * Matches whole path segments, so an unrelated route like `/authoring` is not
 * treated as an auth page.
 */
export function isAuthPath(pathname: string | null | undefined): boolean {
  if (!pathname) return false;
  return (
    pathname === AUTH_PATH_PREFIX || pathname.startsWith(`${AUTH_PATH_PREFIX}/`)
  );
}
