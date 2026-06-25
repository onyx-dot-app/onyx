import { getDomain } from "@/lib/redirectSS";
import { buildUrl } from "@/lib/utilsSS";
import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";
import {
  CRAFT_OAUTH_COOKIE_NAME,
  CRAFT_CONFIGURE_PATH,
} from "@/app/craft/v1/constants";
import { processCookies } from "@/lib/userSS";

const GOOGLE_DRIVE_CREDENTIAL_ID_COOKIE_NAME = "google_drive_credential_id";
const LTI_GOOGLE_DRIVE_OAUTH_COOKIE_NAME = "lti_google_drive_oauth";

function ltiGoogleDrivePopupResponse(
  request: NextRequest,
  status: "success" | "failed"
) {
  const response = new NextResponse(
    `<!doctype html>
<html>
  <head><title>Google Drive authorization</title></head>
  <body>
    <script>
      if (window.opener && !window.opener.closed) {
        window.opener.postMessage(
          { type: "onyx:lti-google-drive-oauth", status: "${status}" },
          ${JSON.stringify(getDomain(request))}
        );
      }
      window.close();
    </script>
    <p>You can close this window and return to the tutor Knowledge page.</p>
  </body>
</html>`,
    {
      headers: {
        "Content-Type": "text/html; charset=utf-8",
      },
    }
  );
  response.cookies.delete(LTI_GOOGLE_DRIVE_OAUTH_COOKIE_NAME);
  response.cookies.delete(GOOGLE_DRIVE_CREDENTIAL_ID_COOKIE_NAME);
  return response;
}

export const GET = async (request: NextRequest) => {
  const requestCookies = await cookies();
  const connector = request.url.includes("gmail") ? "gmail" : "google-drive";
  const isLtiGoogleDriveOAuth =
    connector === "google-drive" &&
    requestCookies.get(LTI_GOOGLE_DRIVE_OAUTH_COOKIE_NAME)?.value === "true";

  const callbackEndpoint = `/manage/connector/${connector}/callback`;
  const url = new URL(buildUrl(callbackEndpoint));
  url.search = request.nextUrl.search;

  const response = await fetch(url.toString(), {
    headers: {
      cookie: processCookies(requestCookies),
    },
  });

  if (isLtiGoogleDriveOAuth) {
    return ltiGoogleDrivePopupResponse(
      request,
      response.ok ? "success" : "failed"
    );
  }

  if (!response.ok) {
    return NextResponse.redirect(
      new URL(
        `/admin/connectors/${connector}?message=oauth_failed`,
        getDomain(request)
      )
    );
  }

  // Check for build mode OAuth flag (redirects to build admin panel)
  const isBuildMode =
    requestCookies.get(CRAFT_OAUTH_COOKIE_NAME)?.value === "true";
  if (isBuildMode) {
    const redirectResponse = NextResponse.redirect(
      new URL(CRAFT_CONFIGURE_PATH, getDomain(request))
    );
    redirectResponse.cookies.delete(CRAFT_OAUTH_COOKIE_NAME);
    return redirectResponse;
  }

  return NextResponse.redirect(
    new URL(`/admin/connectors/${connector}`, getDomain(request))
  );
};
