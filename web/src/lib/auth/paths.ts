import { validateInternalRedirect } from "@/lib/auth/utils";

/** Prefix for unauthenticated routes (login, signup, password reset, etc.). */
export const AUTH_PATH_PREFIX = "/auth";

export const LOGIN_PATH = "/auth/login";

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
