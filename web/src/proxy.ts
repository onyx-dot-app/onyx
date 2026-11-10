import { NextResponse } from "next/server";
import { withSecurityHeaders } from "@/securityHeaders";
import type { NextRequest, ProxyConfig } from "next/server";
import { SERVER_SIDE_ONLY__AUTH_COOKIE_NAME } from "@/lib/constants";
import { loginPath, ORIGINAL_PATH_HEADER } from "@/lib/auth/paths";
import {
  DESKTOP_HANDOFF_PATH,
  isDesktopOAuthCallback,
} from "@/lib/oauth/desktopCallback";

// Route prefixes that never allow anonymous access, so we fast-fail at the edge
// when no auth cookie is present. "/app" is intentionally excluded: it allows
// anonymous access via a runtime (Redis-backed) setting the edge can't read from
// cookies, so it's gated server-side by requireAuth() in
// web/src/app/app/layout.tsx instead.
const PROTECTED_ROUTES = ["/admin", "/agents", "/connector"];

// Public route prefixes (no authentication required)
const PUBLIC_ROUTES = ["/auth", "/anonymous", "/_next", "/api"];

// The API catch-all owns its CSP, preserving backend sandbox restrictions.
// Bypassing Proxy also avoids Next's 10 MiB request-body clone for uploads.
// Page requests still pass through the auth gate, including multipart requests.
// Matchers must be static literals for Next's build-time analysis.
export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|api(?:/|$)).*)",
    // These routes bypass the API catch-all and still need the page CSP.
    "/api",
    "/api/docs/:path*",
    "/api/chat/mcp/oauth/callback",
    "/api/build/sessions/:sessionId/webapp/_next/:hmrEndpoint(hmr|webpack-hmr)",
  ],
} satisfies ProxyConfig;

// Enterprise Edition specific routes (ONLY these get /ee rewriting)
const EE_ROUTES = [
  "/admin/groups",
  "/admin/performance/usage",
  "/admin/spending-limits",
  "/admin/performance/analytics",
  "/admin/performance/query-history",
  "/admin/theme",
  "/admin/performance/custom-analytics",
  "/admin/standard-answer",
  "/admin/export-logs",
  "/admin/scim",
  "/admin/service-accounts",
  "/agents/stats",
];

export async function proxy(request: NextRequest) {
  const pathname = request.nextUrl.pathname;
  const pathWithQuery = pathname + request.nextUrl.search;

  // Set, not merged, so a client cannot supply its own.
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set(ORIGINAL_PATH_HEADER, pathWithQuery);

  // A desktop-started OAuth callback goes back to the app, which holds the
  // session. Serve the handoff page ahead of any auth gate; the URL stays the
  // same, so the page builds the onyx:// link from it.
  if (
    isDesktopOAuthCallback(pathname, request.nextUrl.searchParams.get("state"))
  ) {
    return withSecurityHeaders(
      NextResponse.rewrite(new URL(DESKTOP_HANDOFF_PATH, request.url))
    );
  }

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

    // Require a real auth cookie; the anonymous-user cookie must not satisfy the
    // edge gate for these routes (the server-side role checks reject it anyway).
    if (!authCookie) {
      const loginUrl = new URL(loginPath({ next: pathWithQuery }), request.url);
      return withSecurityHeaders(NextResponse.redirect(loginUrl));
    }
  }

  // Enterprise Edition: Rewrite EE-specific routes to /ee prefix. The /ee
  // layout turns away a deployment whose license does not cover them.
  if (EE_ROUTES.some((route) => pathname.startsWith(route))) {
    const newUrl = new URL(`/ee${pathname}`, request.url);
    return withSecurityHeaders(
      NextResponse.rewrite(newUrl, { request: { headers: requestHeaders } })
    );
  }

  return withSecurityHeaders(
    NextResponse.next({ request: { headers: requestHeaders } })
  );
}
