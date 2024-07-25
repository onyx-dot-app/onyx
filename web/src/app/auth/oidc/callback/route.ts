import { getDomain } from "@/lib/redirectSS";
import { buildUrl } from "@/lib/utilsSS";
import { NextRequest, NextResponse } from "next/server";

export const GET = async (request: NextRequest) => {
  // Wrapper around the FastAPI endpoint /auth/oidc/callback,
  // which adds back a redirect to the main app.
  const url = new URL(buildUrl("/auth/oidc/callback"));
  url.search = request.nextUrl.search;

  const response = await fetch(url.toString());
  const setCookieHeader = response.headers.get("set-cookie");

  if (!setCookieHeader) {
    return NextResponse.redirect(new URL("/auth/error", getDomain(request)));
  }

  const redirectResponse = NextResponse.redirect(
    new URL("/", getDomain(request))
  );
  redirectResponse.headers.set("set-cookie", setCookieHeader);
  return redirectResponse;
};
