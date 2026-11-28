/**
 * Guards the OAuth and OIDC callback wrappers: a 302 from the FastAPI callback
 * is a completed login and must reach the post-login destination with its
 * cookies intact and un-merged, while 4xx/5xx and cookieless 302s go to
 * /auth/error.
 */
import { NextRequest } from "next/server";
import { GET as oauthCallback } from "@/app/auth/oauth/callback/route";
import { GET as oidcCallback } from "@/app/auth/oidc/callback/route";

const APP_DOMAIN = "https://onyx.example.com";

// Next resolves this build-time marker itself, so it has no module to load here.
jest.mock("server-only", () => ({}), { virtual: true });

jest.mock("@/lib/utilsSS", () => ({
  buildUrl: (path: string) => `http://api-server:8080${path}`,
}));

jest.mock("@/lib/redirectSS", () => ({
  getDomain: () => APP_DOMAIN,
}));

const SESSION_COOKIE =
  "fastapiusersauth=session-token; Path=/; HttpOnly; Secure; SameSite=lax";
const PKCE_CLEANUP_COOKIE = "pkce_verifier=; Path=/; Max-Age=0";

// Models the FastAPI GET /auth/{oauth,oidc}/callback responses: success is a
// 302 with cookies, rejection is JSON carrying a detail.
function loginSucceeded(): Response {
  const headers = new Headers({ location: "/app?new_team=true" });
  headers.append("set-cookie", SESSION_COOKIE);
  headers.append("set-cookie", PKCE_CLEANUP_COOKIE);
  return new Response(null, { status: 302, headers });
}

function loginRejected(detail: string): Response {
  const headers = new Headers({ "content-type": "application/json" });
  headers.append("set-cookie", PKCE_CLEANUP_COOKIE);
  return new Response(
    JSON.stringify({ error_code: "VALIDATION_ERROR", detail }),
    {
      status: 400,
      headers,
    }
  );
}

function callbackRequest(path: string): NextRequest {
  return new NextRequest(
    `${APP_DOMAIN}${path}?state=state-value&code=auth-code`
  );
}

afterEach(() => {
  jest.restoreAllMocks();
});

describe.each([
  { name: "oauth", handler: oauthCallback, path: "/auth/oauth/callback" },
  { name: "oidc", handler: oidcCallback, path: "/auth/oidc/callback" },
])("$name callback wrapper", ({ handler, path }) => {
  it("sends a completed login to the post-login destination", async () => {
    jest.spyOn(global, "fetch").mockResolvedValue(loginSucceeded());

    const result = await handler(callbackRequest(path));

    expect(result.headers.get("location")).toBe(
      `${APP_DOMAIN}/app?new_team=true`
    );
    expect(result.headers.getSetCookie()).toContain(SESSION_COOKIE);
  });

  it("re-emits each Set-Cookie separately so attributes cannot bleed", async () => {
    jest.spyOn(global, "fetch").mockResolvedValue(loginSucceeded());

    const result = await handler(callbackRequest(path));

    expect(result.headers.getSetCookie()).toEqual([
      SESSION_COOKIE,
      PKCE_CLEANUP_COOKIE,
    ]);
  });

  it("sends a rejected login to the error page with the backend detail", async () => {
    jest
      .spyOn(global, "fetch")
      .mockResolvedValue(loginRejected("Authorization code exchange failed"));

    const result = await handler(callbackRequest(path));

    const location = new URL(result.headers.get("location") ?? "");
    expect(location.pathname).toBe("/auth/error");
    expect(location.searchParams.get("error")).toBe(
      "Authorization code exchange failed"
    );
    expect(result.headers.getSetCookie()).toContain(PKCE_CLEANUP_COOKIE);
  });

  it("sends an unknown account to account creation", async () => {
    jest
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(null, { status: 401 }));

    const result = await handler(callbackRequest(path));

    expect(new URL(result.headers.get("location") ?? "").pathname).toBe(
      "/auth/create-account"
    );
  });

  it("hands a native app's sign-in back to its deep link", async () => {
    const deepLink = "onyx://auth/callback?code=one-time&state=app-state";
    const headers = new Headers({ location: deepLink });
    headers.append("set-cookie", PKCE_CLEANUP_COOKIE);
    jest
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(null, { status: 302, headers }));

    const result = await handler(callbackRequest(path));

    expect(result.status).toBe(302);
    expect(result.headers.get("location")).toBe(deepLink);
    expect(result.headers.getSetCookie()).toEqual([PKCE_CLEANUP_COOKIE]);
  });

  it.each([
    [
      "a desktop browser to the handoff page",
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_6) AppleWebKit/605.1.15 Safari/605.1.15",
      true,
    ],
    [
      "a phone's auth session straight to the deep link",
      "Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
      false,
    ],
  ])("sends %s", async (_label, userAgent, toPage) => {
    const deepLink = "onyx://auth/callback?code=one-time&state=app-state";
    const headers = new Headers({ location: deepLink });
    headers.append("set-cookie", PKCE_CLEANUP_COOKIE);
    jest
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(null, { status: 302, headers }));
    const request = new NextRequest(
      `${APP_DOMAIN}${path}?state=state-value&code=auth-code`,
      { headers: { "user-agent": userAgent } }
    );

    const result = await handler(request);

    const location = result.headers.get("location") ?? "";
    if (toPage) {
      const page = new URL(location);
      expect(`${page.origin}${page.pathname}`).toBe(
        `${APP_DOMAIN}/auth/app-handoff`
      );
      expect(decodeURIComponent(page.hash.slice(1))).toBe(deepLink);
      expect(page.search).toBe("");
    } else {
      expect(location).toBe(deepLink);
    }
    expect(result.headers.getSetCookie()).toEqual([PKCE_CLEANUP_COOKIE]);
  });

  it("sends a cookieless success to the error page", async () => {
    jest.spyOn(global, "fetch").mockResolvedValue(
      new Response(null, {
        status: 302,
        headers: new Headers({ location: "/app" }),
      })
    );

    const result = await handler(callbackRequest(path));

    expect(new URL(result.headers.get("location") ?? "").pathname).toBe(
      "/auth/error"
    );
  });
});
