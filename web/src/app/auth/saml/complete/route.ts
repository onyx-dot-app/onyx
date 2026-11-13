import { authErrorRedirect } from "@/app/auth/libSS";
import { getDomain } from "@/lib/redirectSS";
import { buildUrl } from "@/lib/utilsSS";
import { NextRequest, NextResponse } from "next/server";

export const GET = async (request: NextRequest) => {
  // Wrapper around the FastAPI endpoint /auth/saml/complete, which checks the
  // login cookie set on /authorize and answers with the session cookie on a
  // redirect to the relay-state destination.
  const url = new URL(buildUrl("/auth/saml/complete"));
  url.search = request.nextUrl.search;
  const cookieHeader = request.headers.get("cookie") || "";

  const response = await fetch(url.toString(), {
    redirect: "manual",
    headers: cookieHeader ? { cookie: cookieHeader } : undefined,
  });

  const location = response.headers.get("location");
  if (response.status !== 302 || !location) {
    return authErrorRedirect(request, response);
  }

  const redirectResponse = NextResponse.redirect(
    new URL(location, getDomain(request)),
    302
  );
  // Re-emit each Set-Cookie separately. Comma-joining would let one cookie's
  // attributes bleed into another's.
  for (const cookie of response.headers.getSetCookie()) {
    redirectResponse.headers.append("set-cookie", cookie);
  }
  return redirectResponse;
};
