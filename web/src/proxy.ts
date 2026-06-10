import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import {
  AuthType,
  SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED,
  SERVER_SIDE_ONLY__AUTH_TYPE,
  SERVER_SIDE_ONLY__AUTH_COOKIE_NAME,
  SERVER_SIDE_ONLY__DISABLE_FRAME_PROTECTION,
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
    // Match everything except /api (proxied to the backend — framing headers
    // are meaningless on API responses and the proxy would add per-request
    // overhead) and Next.js internals/static assets. The catch-all is needed
    // so the clickjacking protection headers below cover every page; the
    // auth check and /ee rewriting are still gated on their route prefixes
    // inside proxy() itself.
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

// frame-ancestors controls who may embed a page in an iframe (clickjacking
// protection). Pages get 'self' only, except the /nrf pages which are
// embedded by the Chrome extension (new tab + side panel). The extension's
// origin can't be pinned to an ID since unpacked dev installs and store
// installs have different IDs, so the chrome-extension: scheme is allowed
// for those routes only.
//
// These headers are emitted here rather than from next.config.js headers()
// because config headers are resolved at build time — emitting them at
// request time is what makes the DISABLE_FRAME_PROTECTION kill switch work
// without a rebuild. Headers set here REPLACE same-named headers from
// next.config.js, which is why the full CSP (shared via security-headers.js)
// is emitted and not just the frame-ancestors directive.
const STRICT_CSP_HEADER = buildCspHeader("'self'");
const EXTENSION_EMBEDDABLE_CSP_HEADER = buildCspHeader(
  "'self' chrome-extension:"
);

function withFrameProtectionHeaders(
  request: NextRequest,
  response: NextResponse
): NextResponse {
  if (SERVER_SIDE_ONLY__DISABLE_FRAME_PROTECTION) {
    return response;
  }

  const pathname = request.nextUrl.pathname;
  const isExtensionEmbeddable =
    pathname === "/nrf" || pathname.startsWith("/nrf/");

  response.headers.set(
    "Content-Security-Policy",
    isExtensionEmbeddable ? EXTENSION_EMBEDDABLE_CSP_HEADER : STRICT_CSP_HEADER
  );
  // Legacy fallback for browsers without CSP frame-ancestors support. Modern
  // browsers ignore this header when frame-ancestors is present, so the
  // chrome-extension: allowance still applies for the /nrf pages.
  response.headers.set("X-Frame-Options", "SAMEORIGIN");
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
