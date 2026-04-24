import { NextRequest, NextResponse } from "next/server";

/**
 * Exposes the current pathname+search as an `x-pathname` request header so
 * server components (reading via `next/headers`) can build accurate post-login
 * redirect targets. See `lib/auth/requireAuth.ts` — fixes #7520 where hitting
 * `/app/shared/{chatId}` unauthenticated would bounce to `/auth/login` with
 * no `next=` param and lose the original URL through SSO.
 */
export function middleware(request: NextRequest) {
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set(
    "x-pathname",
    request.nextUrl.pathname + request.nextUrl.search
  );
  return NextResponse.next({ request: { headers: requestHeaders } });
}

export const config = {
  matcher: "/((?!api|_next/static|_next/image|favicon.ico).*)",
};
