import { getDomain } from "@/lib/redirectSS";
import { buildUrl } from "@/lib/utilsSS";
import { NextRequest, NextResponse } from "next/server";

// have to use this so we don't hit the redirect URL with a `POST` request
const SEE_OTHER_REDIRECT_STATUS = 303;

async function handleSamlCallback(
  request: NextRequest,
  method: "GET" | "POST"
) {
  // Wrapper around the FastAPI endpoint /auth/saml/callback,
  // which adds back a redirect to the main app.
  const url = new URL(buildUrl("/auth/saml/callback"));
  url.search = request.nextUrl.search;

  const fetchOptions: RequestInit = {
    method,
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
  };

  // For POST requests, include form data
  if (method === "POST") {
    fetchOptions.body = await request.formData();
  }

  const response = await fetch(url.toString(), fetchOptions);
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
}

export const GET = async (request: NextRequest) => {
  return handleSamlCallback(request, "GET");
};

export const POST = async (request: NextRequest) => {
  return handleSamlCallback(request, "POST");
};
