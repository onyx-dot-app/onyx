import "server-only";

import { getDomain } from "@/lib/redirectSS";
import { NextRequest, NextResponse } from "next/server";

export async function authErrorRedirect(
  request: NextRequest,
  response: Response,
  redirectStatus?: number
): Promise<NextResponse> {
  const errorUrl = new URL("/auth/error", getDomain(request));
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === "string" && detail) {
      errorUrl.searchParams.set("error", detail);
    }
  } catch {
    // response may not be JSON
  }
  return NextResponse.redirect(errorUrl, redirectStatus);
}
