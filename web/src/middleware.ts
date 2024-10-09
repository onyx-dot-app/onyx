import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED } from "./lib/constants";

// NOTE: have to have the "/:path*" here since NextJS doesn't allow any real JS to
// be run before the config is defined e.g. if we try and do a .map it will complain
const eePaths = [
  "/admin/groups/:path*",
  "/admin/api-key/:path*",
  "/admin/performance/usage/:path*",
  "/admin/performance/query-history/:path*",
  "/admin/whitelabeling/:path*",
  "/admin/performance/custom-analytics/:path*",
  "/admin/standard-answer/:path*",
];

// removes the "/:path*" from the end
const strippedEEPaths = eePaths.map((path) =>
  path.replace(/(.*):\path\*$/, "$1").replace(/\/$/, "")
);

export async function middleware(request: NextRequest) {
  if (SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED) {
    const pathname = request.nextUrl.pathname;

    // Check if the current path is in the eePaths list
    if (strippedEEPaths.some((path) => pathname.startsWith(path))) {
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
  matcher: eePaths,
};
