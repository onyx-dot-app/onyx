import { getDomain } from "@/lib/redirectSS";
import { buildUrl } from "@/lib/utilsSS";
import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";
import {
  GMAIL_AUTH_IS_ADMIN_COOKIE_NAME,
  GOOGLE_DRIVE_AUTH_IS_ADMIN_COOKIE_NAME,
} from "@/lib/constants";
import {
  BUILD_MODE_OAUTH_COOKIE_NAME,
  BUILD_CONFIGURE_PATH,
} from "@/app/build/v1/constants";
import { processCookies } from "@/lib/userSS";

export const GET = async (request: NextRequest) => {
  const requestCookies = await cookies();
  const connector = request.url.includes("gmail") ? "gmail" : "google-drive";
  const callbackEndpoint = `/manage/connector/${connector}/callback`;
  const url = new URL(buildUrl(callbackEndpoint));
  url.search = request.nextUrl.search;

  const response = await fetch(url.toString(), {
    headers: {
      cookie: processCookies(requestCookies),
    },
  });

  if (!response.ok) {
    return NextResponse.redirect(new URL("/auth/error", getDomain(request)));
  }

  // Check for build mode OAuth flag (redirects to build admin panel)
  const isBuildMode =
    requestCookies.get(BUILD_MODE_OAUTH_COOKIE_NAME)?.value === "true";
  if (isBuildMode) {
    const redirectResponse = NextResponse.redirect(
      new URL(BUILD_CONFIGURE_PATH, getDomain(request))
    );
    redirectResponse.cookies.delete(BUILD_MODE_OAUTH_COOKIE_NAME);
    return redirectResponse;
  }

  const authCookieName =
    connector === "gmail"
      ? GMAIL_AUTH_IS_ADMIN_COOKIE_NAME
      : GOOGLE_DRIVE_AUTH_IS_ADMIN_COOKIE_NAME;

  if (requestCookies.get(authCookieName)?.value?.toLowerCase() === "true") {
    return NextResponse.redirect(
      new URL(`/admin/connectors/${connector}`, getDomain(request))
    );
  }

  return NextResponse.redirect(new URL("/user/connectors", getDomain(request)));
};
