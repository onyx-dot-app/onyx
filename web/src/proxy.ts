import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import {
  AuthType,
  SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED,
  SERVER_SIDE_ONLY__AUTH_TYPE,
} from "./lib/constants";

// Authentication cookie name (matches backend: FASTAPI_USERS_AUTH_COOKIE_NAME)
const FASTAPI_USERS_AUTH_COOKIE_NAME = "fastapiusersauth";

// Protected route prefixes (require authentication)
const PROTECTED_ROUTES = ["/chat", "/admin", "/assistants", "/connector"];

// Public route prefixes (no authentication required)
const PUBLIC_ROUTES = ["/auth", "/anonymous", "/_next", "/api"];

// NOTE: have to have the "/:path*" here since NextJS doesn't allow any real JS to
// be run before the config is defined e.g. if we try and do a .map it will complain
export const config = {
  matcher: [
    // Auth-protected routes (for middleware auth check)
    "/chat/:path*",
    "/admin/:path*",
    "/assistants/:path*",
    "/connector/:path*",

    // Enterprise Edition routes (for /ee rewriting)
    // These are ONLY the EE-specific routes that should be rewritten
    "/admin/groups/:path*",
    "/admin/performance/usage/:path*",
    "/admin/performance/query-history/:path*",
    "/admin/theme/:path*",
    "/admin/performance/custom-analytics/:path*",
    "/admin/standard-answer/:path*",
    "/assistants/stats/:path*",

    // Cloud only
    "/admin/billing/:path*",
  ],
};

// Enterprise Edition specific routes (ONLY these get /ee rewriting)
const EE_ROUTES = [
  "/admin/groups",
  "/admin/performance/usage",
  "/admin/performance/query-history",
  "/admin/theme",
  "/admin/performance/custom-analytics",
  "/admin/standard-answer",
  "/assistants/stats",
  "/admin/billing",
];

export async function proxy(request: NextRequest) {
  const pathname = request.nextUrl.pathname;

  // Auth Check: Fast-fail at edge if no cookie (defense in depth)
  // Note: Layouts still do full verification (token validity, roles, etc.)
  // Skip auth checks entirely if auth is disabled
  if (SERVER_SIDE_ONLY__AUTH_TYPE !== AuthType.DISABLED) {
    const isProtectedRoute = PROTECTED_ROUTES.some((route) =>
      pathname.startsWith(route)
    );
    const isPublicRoute = PUBLIC_ROUTES.some((route) =>
      pathname.startsWith(route)
    );

    if (isProtectedRoute && !isPublicRoute) {
      const authCookie = request.cookies.get(FASTAPI_USERS_AUTH_COOKIE_NAME);

      if (!authCookie) {
        const loginUrl = new URL("/auth/login", request.url);
        // Preserve full URL including query params and hash for deep linking
        const fullPath =
          pathname + request.nextUrl.search + request.nextUrl.hash;
        loginUrl.searchParams.set("next", fullPath);
        return NextResponse.redirect(loginUrl);
      }
    }
  }

  // Enterprise Edition: Rewrite EE-specific routes to /ee prefix
  if (SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED) {
    if (EE_ROUTES.some((route) => pathname.startsWith(route))) {
      const newUrl = new URL(`/ee${pathname}`, request.url);
      return NextResponse.rewrite(newUrl);
    }
  }

  return NextResponse.next();
}
