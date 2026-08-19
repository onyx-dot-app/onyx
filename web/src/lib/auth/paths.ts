/** Prefix for unauthenticated routes (login, signup, password reset, etc.). */
export const AUTH_PATH_PREFIX = "/auth";

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
