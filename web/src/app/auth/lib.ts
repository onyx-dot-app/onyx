import { getDomain } from "@/lib/redirectSS";
import { NextRequest, NextResponse } from "next/server";

export const AUTH_ERROR_COOKIE = "__auth_error";

export async function authErrorRedirect(
  request: NextRequest,
  response: Response,
  redirectStatus?: number
): Promise<NextResponse> {
  const redirect = NextResponse.redirect(
    new URL("/auth/error", getDomain(request)),
    redirectStatus
  );
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === "string" && detail) {
      redirect.cookies.set(AUTH_ERROR_COOKIE, detail, {
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
