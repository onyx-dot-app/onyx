import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED } from "./lib/constants";

const eePaths = [
  "/admin/groups",
  "/admin/api-key",
  "/admin/performance/usage",
  "/admin/performance/query-history",
  "/admin/whitelabeling",
  "/admin/performance/custom-analytics",
];
const eePathsForMatcher = eePaths.map((path) => `${path}/:path*`);

export async function middleware(request: NextRequest) {
  if (SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED) {
    const pathname = request.nextUrl.pathname;

    // Check if the current path is in the eePaths list
    if (eePaths.some((path) => pathname.startsWith(path))) {
      // Add '/ee' to the beginning of the pathname
      const newPathname = `/ee${pathname}`;

      // Create a new URL with the modified pathname
      const newUrl = new URL(newPathname, request.url);

      // Rewrite to the new URL
      return NextResponse.rewrite(newUrl);
    }
  }

  // Continue with the response if no rewrite is needed
  return NextResponse.next();
}

// Specify the paths that the middleware should run for
export const config = {
  matcher: eePathsForMatcher,
};
