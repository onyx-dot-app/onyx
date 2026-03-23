import { getDomain } from "@/lib/redirectSS";
import { NextRequest, NextResponse } from "next/server";

export const AUTH_ERROR_COOKIE = "__auth_error";

export async function authErrorRedirect(
  request: NextRequest,
  response: Response
): Promise<NextResponse> {
  const redirect = NextResponse.redirect(
    new URL("/auth/error", getDomain(request))
  );
  try {
    const body = await response.json();
    if (body?.error_code && body?.detail) {
      redirect.cookies.set(AUTH_ERROR_COOKIE, body.detail, {
        httpOnly: true,
        secure: true,
        sameSite: "strict",
        maxAge: 60,
        path: "/auth/error",
      });
    }
  } catch {
    // response may not be JSON
  }
  return redirect;
}

export async function requestEmailVerification(email: string) {
  return await fetch("/api/auth/request-verify-token", {
    headers: {
      "Content-Type": "application/json",
    },
    method: "POST",
    body: JSON.stringify({
      email: email,
    }),
  });
}
