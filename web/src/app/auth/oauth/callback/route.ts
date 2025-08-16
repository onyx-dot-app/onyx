import { getDomain } from "@/lib/redirectSS";
import { buildUrl } from "@/lib/utilsSS";
import { NextRequest, NextResponse } from "next/server";
import { jwtDecode } from "jwt-decode";

export const GET = async (request: NextRequest) => {
  // Wrapper around the FastAPI endpoint /auth/oauth/callback,
  // which adds back a redirect to the main app.
  const url = new URL(buildUrl("/auth/oauth/callback"));
  url.search = request.nextUrl.search;

  // Set 'redirect' to 'manual' to prevent automatic redirection
  const response = await fetch(url.toString(), { redirect: "manual" });
  const setCookieHeader = response.headers.get("set-cookie");

  if (response.status === 401) {
    return NextResponse.redirect(
      new URL("/auth/create-account", getDomain(request))
    );
  }

  if (!setCookieHeader) {
    return NextResponse.redirect(new URL("/auth/error", getDomain(request)));
  }

  let destination = "/";
  let state = request.nextUrl.searchParams.get("state");

  if (state) {
    try {
      const decodedState = jwtDecode(state);

      destination = (decodedState as any).next_url || "/";
    } catch (e) {
      console.error("Failed to decode JWT state", e);
    }
  }

  // Get the redirect URL from the backend's 'Location' header, or default to '/'
  const redirectUrl = response.headers.get("location") || destination;

  const redirectResponse = NextResponse.redirect(
    new URL(redirectUrl, getDomain(request))
  );

  redirectResponse.headers.set("set-cookie", setCookieHeader);
  return redirectResponse;
};
