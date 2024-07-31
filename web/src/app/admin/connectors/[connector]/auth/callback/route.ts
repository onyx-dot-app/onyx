import { getDomain } from "@/lib/redirectSS";
import { buildUrl } from "@/lib/utilsSS";
import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";
import {
  GMAIL_AUTH_IS_ADMIN_COOKIE_NAME,
  GOOGLE_DRIVE_AUTH_IS_ADMIN_COOKIE_NAME,
} from "@/lib/constants";
import { processCookies } from "@/lib/userSS";

export const GET = async (request: NextRequest) => {
  const connector = request.url.includes("gmail") ? "gmail" : "google-drive";
  const callbackEndpoint = `/manage/connector/${connector}/callback`;
  const url = new URL(buildUrl(callbackEndpoint));
  url.search = request.nextUrl.search;

  const response = await fetch(url.toString(), {
    headers: {
      cookie: processCookies(cookies()),
    },
  });

  if (!response.ok) {
    console.log(
      `Error in ${connector} callback:`,
      (await response.json()).detail
    );
    return NextResponse.redirect(new URL("/auth/error", getDomain(request)));
  }

  const authCookieName =
    connector === "gmail"
      ? GMAIL_AUTH_IS_ADMIN_COOKIE_NAME
      : GOOGLE_DRIVE_AUTH_IS_ADMIN_COOKIE_NAME;

  if (cookies().get(authCookieName)?.value?.toLowerCase() === "true") {
    return NextResponse.redirect(
      new URL(`/admin/connectors/${connector}`, getDomain(request))
    );
  }

  return NextResponse.redirect(new URL("/user/connectors", getDomain(request)));
};
