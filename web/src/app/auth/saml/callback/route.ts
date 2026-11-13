import { authErrorRedirect } from "@/app/auth/libSS";
import { getDomain } from "@/lib/redirectSS";
import { buildUrl } from "@/lib/utilsSS";
import { NextRequest, NextResponse } from "next/server";

// have to use this so we don't hit the redirect URL with a `POST` request
const SEE_OTHER_REDIRECT_STATUS = 303;

async function handleSamlCallback(
  request: NextRequest,
  method: "GET" | "POST"
) {
  // Wrapper around the FastAPI endpoint /auth/saml/callback. The backend
  // validates the response and answers with a 303 to /auth/saml/complete,
  // which the browser must follow itself so its login cookie travels with it.
  const url = new URL(buildUrl("/auth/saml/callback"));
  url.search = request.nextUrl.search;

  const fetchOptions: RequestInit = {
    method,
    headers: {},
    redirect: "manual",
  };

  // For POST requests, include form data
  if (method === "POST") {
    fetchOptions.body = await request.formData();
  }

  // OneLogin python toolkit only supports HTTP-POST binding for SAMLResponse.
  // If the IdP returned SAMLResponse via query parameters (GET), convert to POST.
  if (method === "GET") {
    const samlResponse = request.nextUrl.searchParams.get("SAMLResponse");
    const relayState = request.nextUrl.searchParams.get("RelayState");
    if (samlResponse) {
      const formData = new FormData();
      formData.set("SAMLResponse", samlResponse);
      if (relayState) {
        formData.set("RelayState", relayState);
      }
      // Clear query on backend URL and send as POST with form body
      url.search = "";
      fetchOptions.method = "POST";
      fetchOptions.body = formData;
    }
  }

  const response = await fetch(url.toString(), fetchOptions);

  const location = response.headers.get("location");
  if (response.status !== SEE_OTHER_REDIRECT_STATUS || !location) {
    return authErrorRedirect(request, response, SEE_OTHER_REDIRECT_STATUS);
  }

  return NextResponse.redirect(
    new URL(location, getDomain(request)),
    SEE_OTHER_REDIRECT_STATUS
  );
}

export const GET = async (request: NextRequest) => {
  return handleSamlCallback(request, "GET");
};

export const POST = async (request: NextRequest) => {
  return handleSamlCallback(request, "POST");
};
