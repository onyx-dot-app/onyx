import { User, UserRole } from "@/lib/types";
import {
  AuthTypeMetadata,
  getAuthTypeMetadataSS,
  getCurrentUserSS,
} from "@/lib/userSS";

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

  const authDisabled = authTypeMetadata?.authType === "disabled";

  // If auth is not disabled and user is not logged in, redirect to login
  if (!authDisabled && !user) {
    return {
      user,
      authTypeMetadata,
      redirect: "/auth/login",
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
  const authDisabled = authTypeMetadata?.authType === "disabled";

  // Check if user has an allowed role (only if auth is not disabled)
  if (!authDisabled && user && !ADMIN_ALLOWED_ROLES.includes(user.role)) {
    return {
      user,
      authTypeMetadata,
      redirect: "/chat",
    };
  }

  return authResult;
}
