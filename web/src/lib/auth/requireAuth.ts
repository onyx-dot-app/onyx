import { headers } from "next/headers";
import { User, UserRole } from "@/lib/types";
import { getCurrentUserSS } from "@/lib/users/svcSS";
import { getAuthTypeMetadataSS } from "@/lib/auth/svcSS";
import { AuthTypeMetadata } from "@/lib/auth/types";
import { AuthType } from "@/lib/constants";
import { validateInternalRedirect } from "./redirectValidation";

/**
 * Result of an authentication check.
 * If redirect is set, the caller should redirect immediately.
 */
export interface AuthCheckResult {
  user: User | null;
  authTypeMetadata: AuthTypeMetadata | null;
  redirect?: string;
}

/**
 * Build the login redirect target, preserving the current pathname as a
 * `?next=…` query param so the user can be returned to the original page
 * after SSO. The `x-pathname` request header is injected by `middleware.ts`.
 *
 * The rest of the `next=` plumbing already works — the login page reads
 * `searchParams.next`, the SSO handoff threads it into OAuth/OIDC/SAML
 * state, and the backend restores it on callback — but nothing populated
 * the param at this (layout-level) redirect before (#7520).
 */
async function buildLoginRedirect(): Promise<string> {
  try {
    const pathname = (await headers()).get("x-pathname");
    const safe = validateInternalRedirect(pathname);
    // Skip when the header is missing, the path failed validation, or we're
    // already on the login page (avoids ?next=/auth/login recursion).
    if (!safe || safe.startsWith("/auth/login")) {
      return "/auth/login";
    }
    return `/auth/login?next=${encodeURIComponent(safe)}`;
  } catch {
    // `headers()` is not available during static generation / build-time
    // prerendering; fall back to a bare login redirect in those cases.
    return "/auth/login";
  }
}

/**
 * Requires that the user is authenticated.
 * If not authenticated and auth is enabled, returns a redirect to login.
 * Also checks email verification if required.
 *
 * @returns AuthCheckResult with user, auth metadata, and optional redirect
 *
 * @example
 * ```typescript
 * const authResult = await requireAuth();
 * if (authResult.redirect) {
 *   return redirect(authResult.redirect);
 * }
 * // User is authenticated, proceed with logic
 * const { user } = authResult;
 * ```
 */
export async function requireAuth(): Promise<AuthCheckResult> {
  // Fetch auth information
  let user: User | null = null;
  let authTypeMetadata: AuthTypeMetadata | null = null;

  try {
    [authTypeMetadata, user] = await Promise.all([
      getAuthTypeMetadataSS(),
      getCurrentUserSS(),
    ]);
  } catch (e) {
    console.log(`Failed to fetch auth information - ${e}`);
  }

  // If user is not logged in, redirect to login (preserving the intended
  // destination as ?next=… so SSO can return the user to it).
  if (!user) {
    return {
      user,
      authTypeMetadata,
      redirect: await buildLoginRedirect(),
    };
  }

  // Check email verification if required
  if (user && !user.is_verified && authTypeMetadata?.requiresVerification) {
    return {
      user,
      authTypeMetadata,
      redirect: "/auth/waiting-on-verification",
    };
  }

  return {
    user,
    authTypeMetadata,
  };
}

// Allowlist of roles that can access admin pages (all roles except BASIC)
const ADMIN_ALLOWED_ROLES = [
  UserRole.ADMIN,
  UserRole.CURATOR,
  UserRole.GLOBAL_CURATOR,
];

/**
 * Requires that the user is authenticated AND has admin role.
 * If not authenticated, redirects to login.
 * If authenticated but not admin, redirects to /chat.
 * Also checks email verification if required.
 *
 * @returns AuthCheckResult with user, auth metadata, and optional redirect
 *
 * @example
 * ```typescript
 * const authResult = await requireAdminAuth();
 * if (authResult.redirect) {
 *   return redirect(authResult.redirect);
 * }
 * // User is authenticated admin, proceed with admin logic
 * const { user } = authResult;
 * ```
 */
export async function requireAdminAuth(): Promise<AuthCheckResult> {
  const authResult = await requireAuth();

  // If already has a redirect (not authenticated or not verified), return it
  if (authResult.redirect) {
    return authResult;
  }

  const { user, authTypeMetadata } = authResult;

  // Check if user has an allowed role
  if (user && !ADMIN_ALLOWED_ROLES.includes(user.role)) {
    return {
      user,
      authTypeMetadata,
      redirect: "/app",
    };
  }

  return authResult;
}
