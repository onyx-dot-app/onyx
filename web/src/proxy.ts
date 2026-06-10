import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import {
  AuthType,
  SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED,
  SERVER_SIDE_ONLY__AUTH_TYPE,
  SERVER_SIDE_ONLY__AUTH_COOKIE_NAME,
  SERVER_SIDE_ONLY__NRF_PAGE_ENABLED,
} from "./lib/constants";
import { buildCspHeader } from "./lib/security-headers";

// Authentication cookie names (matches backend constants)
const ANONYMOUS_USER_COOKIE_NAME = "onyx_anonymous_user";

// Protected route prefixes (require authentication)
const PROTECTED_ROUTES = ["/app", "/admin", "/agents", "/connector"];

// Public route prefixes (no authentication required)
const PUBLIC_ROUTES = ["/auth", "/anonymous", "/_next", "/api"];

// NOTE: have to have the "/:path*" here since NextJS doesn't allow any real JS to
// be run before the config is defined e.g. if we try and do a .map it will complain
export const config = {
  matcher: [
    // Everything except /api and Next internals/static assets, so the frame
    // protection headers cover every page. Auth check and /ee rewriting are
    // still gated on their route prefixes inside proxy().
    "/((?!api$|api/|_next/|favicon.ico).*)",
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
  "/agents/stats",
];

// Clickjacking protection. Pages get frame-ancestors 'self'; deployments
// that opt in via ENABLE_NRF_PAGE relax the /nrf pages to chrome-extension:
// so the Chrome extension can embed them (its ID differs between store and
// unpacked installs, so the scheme is allowed instead). Emitted here (not
// next.config.js, which is resolved at build time) so the switch works at
// runtime; see security-headers.js for why the full CSP must be emitted.
const STRICT_CSP_HEADER = buildCspHeader("'self'");
const EXTENSION_EMBEDDABLE_CSP_HEADER = buildCspHeader(
  "'self' chrome-extension:"
);

function isNrfRoute(pathname: string): boolean {
  return pathname === "/nrf" || pathname.startsWith("/nrf/");
}

function withFrameProtectionHeaders(
  request: NextRequest,
  response: NextResponse
): NextResponse {
  const pathname = request.nextUrl.pathname;
  const isExtensionEmbeddable =
    SERVER_SIDE_ONLY__NRF_PAGE_ENABLED && isNrfRoute(pathname);

  response.headers.set(
    "Content-Security-Policy",
    isExtensionEmbeddable ? EXTENSION_EMBEDDABLE_CSP_HEADER : STRICT_CSP_HEADER
  );
  // Legacy fallback; browsers ignore XFO when frame-ancestors is present,
  // so the /nrf extension allowance above still applies.
  response.headers.set("X-Frame-Options", "SAMEORIGIN");
  return response;
}

export async function proxy(request: NextRequest) {
  const pathname = request.nextUrl.pathname;

  // Unless a deployment opts in, the /nrf pages are unreachable and the
  // chrome-extension: allowance is never emitted, so the extension can't
  // frame anything — the redirect target / carries frame-ancestors 'self'.
  if (!SERVER_SIDE_ONLY__NRF_PAGE_ENABLED && isNrfRoute(pathname)) {
    return withFrameProtectionHeaders(
      request,
      NextResponse.redirect(new URL("/", request.url))
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
    const anonymousCookie = request.cookies.get(ANONYMOUS_USER_COOKIE_NAME);

    // Allow access if user has either a regular auth cookie or anonymous user cookie
    if (!authCookie && !anonymousCookie) {
      const loginUrl = new URL("/auth/login", request.url);
      // Preserve full URL including query params and hash for deep linking
      const fullPath = pathname + request.nextUrl.search + request.nextUrl.hash;
      loginUrl.searchParams.set("next", fullPath);
      return withFrameProtectionHeaders(
        request,
        NextResponse.redirect(loginUrl)
      );
    }
  }

  // Enterprise Edition: Rewrite EE-specific routes to /ee prefix
  if (SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED) {
    if (EE_ROUTES.some((route) => pathname.startsWith(route))) {
      const newUrl = new URL(`/ee${pathname}`, request.url);
      return withFrameProtectionHeaders(request, NextResponse.rewrite(newUrl));
    }
  }

  return withFrameProtectionHeaders(request, NextResponse.next());
}
