import { authErrorRedirect } from "@/app/auth/libSS";
import { getDomain } from "@/lib/redirectSS";
import { buildUrl } from "@/lib/utilsSS";
import { NextRequest, NextResponse } from "next/server";

// A provider-row Google flow round-trips its row name inside the signed
// state, while the env-credential flow does not. Routing only, the backend
// still verifies the signature.
function isProviderRowState(state: string | null): boolean {
  if (!state) return false;
  try {
    const payload = JSON.parse(
      Buffer.from(state.split(".")[1] ?? "", "base64url").toString("utf8")
    );
    return typeof payload.provider_name === "string";
  } catch {
    return false;
  }
}

export const GET = async (request: NextRequest) => {
  // Wrapper around the FastAPI callback, which adds back a redirect to the
  // main app. Migrated provider rows allowlist this URL at the IdP, so their
  // flows land here too and are dispatched to the row callback.
  const rowFlow = isProviderRowState(request.nextUrl.searchParams.get("state"));
  const url = new URL(
    buildUrl(rowFlow ? "/auth/oidc/callback" : "/auth/oauth/callback")
  );
  url.search = request.nextUrl.search;
  const cookieHeader = request.headers.get("cookie") || "";

  // Set 'redirect' to 'manual' to prevent automatic redirection
  const response = await fetch(url.toString(), {
    redirect: "manual",
    headers: cookieHeader ? { cookie: cookieHeader } : undefined,
  });
  const setCookieHeader = response.headers.get("set-cookie");

  if (response.status === 401) {
    return NextResponse.redirect(
      new URL("/auth/create-account", getDomain(request))
    );
  }

  if (!setCookieHeader) {
    return authErrorRedirect(request, response);
  }

  // Get the redirect URL from the backend's 'Location' header, or default to '/'
  const redirectUrl = response.headers.get("location") || "/";

  const redirectResponse = NextResponse.redirect(
    new URL(redirectUrl, getDomain(request))
  );

  redirectResponse.headers.set("set-cookie", setCookieHeader);
  return redirectResponse;
};
