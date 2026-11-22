import { authErrorRedirect } from "@/app/auth/libSS";
import { getDomain } from "@/lib/redirectSS";
import { buildUrl } from "@/lib/utilsSS";
import { NextRequest, NextResponse } from "next/server";
import { appSignInRedirect, isAppSignInHandoff } from "@/lib/auth/appHandoff";

export const GET = async (request: NextRequest) => {
  // Wrapper around the FastAPI endpoint /auth/oidc/callback,
  // which adds back a redirect to the main app.
  const url = new URL(buildUrl("/auth/oidc/callback"));
  url.search = request.nextUrl.search;
  const cookieHeader = request.headers.get("cookie") || "";

  // Set 'redirect' to 'manual' to prevent automatic redirection
  const response = await fetch(url.toString(), {
    redirect: "manual",
    headers: cookieHeader ? { cookie: cookieHeader } : undefined,
  });
  if (response.status === 401) {
    return NextResponse.redirect(
      new URL("/auth/create-account", getDomain(request))
    );
  }

  // A completed login arrives as a 302, so 4xx/5xx is the failure signal here.
  // Error responses carry the PKCE cleanup cookie, so forward it too.
  if (response.status >= 400) {
    const errorRedirect = await authErrorRedirect(request, response);
    for (const cookie of response.headers.getSetCookie()) {
      errorRedirect.headers.append("set-cookie", cookie);
    }
    return errorRedirect;
  }

  // A native app's sign-in ends with its deep link and no web session cookie.
  const location = response.headers.get("location");
  if (isAppSignInHandoff(location)) {
    // Keep the backend's cookie cleanup (e.g. the PKCE verifier deletion).
    const handoff = NextResponse.redirect(
      appSignInRedirect(
        location,
        request.headers.get("user-agent"),
        getDomain(request)
      ),
      302
    );
    for (const cookie of response.headers.getSetCookie()) {
      handoff.headers.append("set-cookie", cookie);
    }
    return handoff;
  }

  const setCookieHeaders = response.headers.getSetCookie();
  if (setCookieHeaders.length === 0) {
    return authErrorRedirect(request, response);
  }

  // Get the redirect URL from the backend's 'Location' header, or default to '/'
  const redirectUrl = response.headers.get("location") || "/";

  const redirectResponse = NextResponse.redirect(
    new URL(redirectUrl, getDomain(request))
  );

  // Re-emit each Set-Cookie separately. Comma-joining would let one cookie's
  // attributes (e.g. the PKCE deletion's Max-Age=0) bleed into the session's.
  for (const cookie of setCookieHeaders) {
    redirectResponse.headers.append("set-cookie", cookie);
  }
  return redirectResponse;
};
