import { getDomain } from "@/lib/redirectSS";
import { buildUrl } from "@/lib/utilsSS";
import { NextRequest, NextResponse } from "next/server";

// have to use this so we don't hit the redirect URL with a `POST` request
const SEE_OTHER_REDIRECT_STATUS = 303;

export const POST = async (request: NextRequest) => {
  // Wrapper around the FastAPI endpoint /auth/saml/callback,
  // which adds back a redirect to the main app.
  const url = new URL(buildUrl("/auth/saml/callback"));
  url.search = request.nextUrl.search;

  const response = await fetch(url.toString(), {
    method: "POST",
    body: await request.formData(),
    headers: {
      "X-Forwarded-Host":
        request.headers.get("X-Forwarded-Host") ||
        request.headers.get("host") ||
        "",
      "X-Forwarded-Port":
        request.headers.get("X-Forwarded-Port") ||
        new URL(request.url).port ||
        "",
    },
  });
  const setCookieHeader = response.headers.get("set-cookie");

  if (!setCookieHeader) {
    return NextResponse.redirect(
      new URL("/auth/error", getDomain(request)),
      SEE_OTHER_REDIRECT_STATUS
    );
  }

  const redirectResponse = NextResponse.redirect(
    new URL("/", getDomain(request)),
    SEE_OTHER_REDIRECT_STATUS
  );
  redirectResponse.headers.set("set-cookie", setCookieHeader);
  return redirectResponse;
};
