/** The proxy stamps the request path and query into ORIGINAL_PATH_HEADER on
 * pass-through and on the EE rewrite; requireAuth() turns it into `next`. */
import { NextRequest } from "next/server";
import { cookies, headers } from "next/headers";
import { proxy } from "@/proxy";
import { requireAuth } from "@/lib/auth/svcSS";
import { ORIGINAL_PATH_HEADER } from "@/lib/auth/paths";
import { SERVER_SIDE_ONLY__AUTH_COOKIE_NAME } from "@/lib/constants";

const APP_DOMAIN = "https://onyx.example.com";
const STAMPED = `x-middleware-request-${ORIGINAL_PATH_HEADER}`;

// Next resolves this build-time marker itself, so it has no module to load here.
jest.mock("server-only", () => ({}), { virtual: true });

jest.mock("@/lib/utilsSS", () => ({
  buildUrl: (path: string) => `http://api-server:8080${path}`,
}));

jest.mock("next/headers", () => ({
  headers: jest.fn(),
  cookies: jest.fn(),
}));

// Toggled per test so both proxy branches run against one module instance.
const mockFlags = { ee: false };
jest.mock("@/lib/constants", () => ({
  ...jest.requireActual("@/lib/constants"),
  get SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED() {
    return mockFlags.ee;
  },
}));

const mockHeaders = headers as jest.MockedFunction<typeof headers>;
const mockCookies = cookies as jest.MockedFunction<typeof cookies>;

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe("proxy stamps the original path", () => {
  beforeEach(() => {
    mockFlags.ee = false;
  });

  test("on a pass-through, query included", async () => {
    const res = await proxy(
      new NextRequest(`${APP_DOMAIN}/app?user-prompt=hello&sources=slack`)
    );
    expect(res.headers.get(STAMPED)).toBe(
      "/app?user-prompt=hello&sources=slack"
    );
  });

  test("on the EE rewrite", async () => {
    mockFlags.ee = true;
    const res = await proxy(
      new NextRequest(`${APP_DOMAIN}/admin/groups?tab=members`, {
        headers: { cookie: `${SERVER_SIDE_ONLY__AUTH_COOKIE_NAME}=session` },
      })
    );
    expect(res.headers.get("x-middleware-rewrite")).toBe(
      `${APP_DOMAIN}/ee/admin/groups`
    );
    expect(res.headers.get(STAMPED)).toBe("/admin/groups?tab=members");
  });

  test("replaces a value the client supplied", async () => {
    const res = await proxy(
      new NextRequest(`${APP_DOMAIN}/app`, {
        headers: { [ORIGINAL_PATH_HEADER]: "/evil" },
      })
    );
    expect(res.headers.get(STAMPED)).toBe("/app");
  });

  test("sends an unauthenticated admin request to login with next", async () => {
    const res = await proxy(
      new NextRequest(`${APP_DOMAIN}/admin/users?tab=invited`)
    );
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe(
      `${APP_DOMAIN}/auth/login?next=%2Fadmin%2Fusers%3Ftab%3Dinvited`
    );
  });
});

describe("requireAuth turns the stamped path into next", () => {
  beforeEach(() => {
    mockCookies.mockResolvedValue({
      getAll: () => [],
    } as unknown as Awaited<ReturnType<typeof cookies>>);
    // Mock GET /auth/type (public) and GET /me (no session, 403).
    jest.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      return url.endsWith("/auth/type")
        ? jsonResponse(200, {
            multi_tenant: false,
            requires_verification: false,
            has_users: true,
          })
        : jsonResponse(403, { detail: "Forbidden" });
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  function stamp(value: string | null) {
    const requestHeaders = new Headers();
    if (value !== null) requestHeaders.set(ORIGINAL_PATH_HEADER, value);
    mockHeaders.mockResolvedValue(
      requestHeaders as unknown as Awaited<ReturnType<typeof headers>>
    );
  }

  test("carries the deep link", async () => {
    stamp("/app?user-prompt=hello&sources=slack");
    const result = await requireAuth();
    expect(result.user).toBeNull();
    expect(result.redirect).toBe(
      "/auth/login?next=%2Fapp%3Fuser-prompt%3Dhello%26sources%3Dslack"
    );
  });

  test("falls back to the bare login page without the header", async () => {
    stamp(null);
    expect((await requireAuth()).redirect).toBe("/auth/login");
  });

  test("drops a value that is not an internal path", async () => {
    stamp("//evil.example.com/app");
    expect((await requireAuth()).redirect).toBe("/auth/login");
  });
});
