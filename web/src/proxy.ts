import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import {
  AuthType,
  SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED,
  SERVER_SIDE_ONLY__AUTH_TYPE,
  SERVER_SIDE_ONLY__AUTH_COOKIE_NAME,
} from "./lib/constants";

// Authentication cookie names (matches backend constants)
const ANONYMOUS_USER_COOKIE_NAME = "onyx_anonymous_user";

// Protected route prefixes (require authentication)
const PROTECTED_ROUTES = ["/app", "/admin", "/agents", "/connector"];

// Public route prefixes (no authentication required)
const PUBLIC_ROUTES = ["/auth", "/anonymous", "/_next", "/api"];

// The CSP is emitted here, not in next.config.js `headers()` (which is baked
// into the build), so WEB_FRAME_PROTECTION_ENABLED is read at runtime and
// applies on restart without a rebuild.
//
// frame-ancestors controls who may embed Onyx in an <iframe>. On by default;
// WEB_FRAME_PROTECTION_ENABLED=false drops it so any origin may frame Onyx.
// chrome-extension:/moz-extension: are app-wide (the extension iframes every
// route, not just /nrf) and cover both Chromium and Firefox builds.
// X-Frame-Options is omitted: it can't express the extension allowance and
// modern browsers honor frame-ancestors.
const frameProtectionEnabled =
  process.env.WEB_FRAME_PROTECTION_ENABLED?.toLowerCase() !== "false";

// NEXT_PUBLIC_* and NODE_ENV are inlined at build, so this stays build-time —
// only the frame-ancestors flag above is runtime.
const upgradeInsecureRequests =
  process.env.NEXT_PUBLIC_CLOUD_ENABLED === "true" &&
  process.env.NODE_ENV !== "development";

const CSP_HEADER = [
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;",
  "font-src 'self' https://fonts.gstatic.com;",
  "object-src 'none';",
  "base-uri 'self';",
  "form-action 'self';",
  frameProtectionEnabled
    ? "frame-ancestors 'self' chrome-extension: moz-extension:;"
    : "",
  upgradeInsecureRequests ? "upgrade-insecure-requests;" : "",
]
  .filter(Boolean)
  .join(" ");

// Match every route except Next.js internals and static assets so the CSP rides
// on all document responses. The auth/EE logic below is pathname-gated, so the
// broader match doesn't change its behavior. Matchers must be static strings —
// no JS runs before `config` is read.
export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};

// Enterprise Edition specific routes (ONLY these get /ee rewriting)
const EE_ROUTES = [
  "/admin/groups",
  "/admin/performance/usage",
  "/admin/performance/query-history",
  "/admin/theme",
  "/admin/performance/custom-analytics",
  "/admin/standard-answer",
  "/agents/stats",
];

function withSecurityHeaders(response: NextResponse): NextResponse {
  response.headers.set("Content-Security-Policy", CSP_HEADER);
  return response;
}

export async function proxy(request: NextRequest) {
  const pathname = request.nextUrl.pathname;

  // Auth Check: Fast-fail at edge if no cookie (defense in depth)
  // Note: Layouts still do full verification (token validity, roles, etc.)
  const isProtectedRoute = PROTECTED_ROUTES.some((route) =>
    pathname.startsWith(route)
  );
  const isPublicRoute = PUBLIC_ROUTES.some((route) =>
    pathname.startsWith(route)
  );

  if (isProtectedRoute && !isPublicRoute) {
    const authCookie = request.cookies.get(SERVER_SIDE_ONLY__AUTH_COOKIE_NAME);
    const anonymousCookie = request.cookies.get(ANONYMOUS_USER_COOKIE_NAME);

    // Allow access if user has either a regular auth cookie or anonymous user cookie
    if (!authCookie && !anonymousCookie) {
      const loginUrl = new URL("/auth/login", request.url);
      // Preserve full URL including query params and hash for deep linking
      const fullPath = pathname + request.nextUrl.search + request.nextUrl.hash;
      loginUrl.searchParams.set("next", fullPath);
      return withSecurityHeaders(NextResponse.redirect(loginUrl));
    }
  }

  // Enterprise Edition: Rewrite EE-specific routes to /ee prefix
  if (SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED) {
    if (EE_ROUTES.some((route) => pathname.startsWith(route))) {
      const newUrl = new URL(`/ee${pathname}`, request.url);
      return withSecurityHeaders(NextResponse.rewrite(newUrl));
    }
  }

  return withSecurityHeaders(NextResponse.next());
}
