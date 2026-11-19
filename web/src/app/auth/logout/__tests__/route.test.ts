/**
 * The logout route proxies to the backend and must expire the auth cookie
 * whether the backend logout succeeds, fails, or cannot be reached.
 */
import { NextRequest } from "next/server";
import { POST as logout } from "@/app/auth/logout/route";
import { SERVER_SIDE_ONLY__AUTH_COOKIE_NAME } from "@/lib/constants";

// Next resolves this build-time marker itself, so it has no module to load here.
jest.mock("server-only", () => ({}), { virtual: true });

jest.mock("@/lib/utilsSS", () => ({
  buildUrl: (path: string) => `http://api-server:8080${path}`,
}));

function logoutRequest(): NextRequest {
  return new NextRequest("https://onyx.example.com/auth/logout", {
    method: "POST",
    headers: { cookie: `${SERVER_SIDE_ONLY__AUTH_COOKIE_NAME}=dead-token` },
  });
}

function expectAuthCookieCleared(response: Response): void {
  const cleared = response.headers
    .getSetCookie()
    .filter((cookie) =>
      cookie.startsWith(`${SERVER_SIDE_ONLY__AUTH_COOKIE_NAME}=;`)
    );
  expect(cleared).toHaveLength(1);
  expect(cleared[0]).toContain("Max-Age=0");
  expect(cleared[0]).toContain("path=/");
}

afterEach(() => {
  jest.restoreAllMocks();
});

describe("logout route", () => {
  it("clears the auth cookie when the backend logout succeeds", async () => {
    jest
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(null, { status: 204 }));

    const response = await logout(logoutRequest());

    expect(response.status).toBe(204);
    expectAuthCookieCleared(response);
  });

  it("clears the auth cookie and keeps the backend error when logout fails", async () => {
    const body = JSON.stringify({
      error_code: "SESSION_UNRECOGNIZED",
      detail: "Session not recognized. Please log in again.",
    });
    jest
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(body, { status: 403 }));

    const response = await logout(logoutRequest());

    expect(response.status).toBe(403);
    expect(await response.text()).toBe(body);
    expectAuthCookieCleared(response);
  });

  it("clears the auth cookie when the backend cannot be reached", async () => {
    jest
      .spyOn(global, "fetch")
      .mockRejectedValue(new TypeError("fetch failed"));
    jest.spyOn(console, "error").mockImplementation(() => {});

    const response = await logout(logoutRequest());

    expect(response.status).toBe(204);
    expectAuthCookieCleared(response);
  });
});
