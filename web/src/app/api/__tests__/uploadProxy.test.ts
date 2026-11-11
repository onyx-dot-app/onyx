import { unstable_doesMiddlewareMatch } from "next/experimental/testing/server";
import { NextRequest, NextResponse } from "next/server";
import { config, proxy } from "@/proxy";
import { GET, POST } from "@/app/api/[...path]/route";
import { ORIGINAL_PATH_HEADER } from "@/lib/auth/paths";

const origin = "http://localhost:3000";

// Exercise Next's matcher rather than calling proxy() on excluded requests.
describe("API catch-all routing", () => {
  test.each([
    "/api/skills/custom",
    "/api/user/projects/file/upload",
    "/api/manage/admin/connector/file",
    "/api/build/user-library/files",
  ])("bypasses the page proxy for upload route %s", (path) => {
    expect(
      unstable_doesMiddlewareMatch({
        config,
        url: origin + path,
      })
    ).toBe(false);
  });

  test.each(["/admin/users", "/agents", "/connector", "/app", "/apiary"])(
    "keeps the page proxy for %s",
    (path) => {
      expect(
        unstable_doesMiddlewareMatch({
          config,
          url: origin + path,
        })
      ).toBe(true);
    }
  );

  test.each(["/api/auth/login", "/api/health", "/api/chat/file/test"])(
    "bypasses the page proxy for non-upload route %s",
    (path) => {
      expect(unstable_doesMiddlewareMatch({ config, url: origin + path })).toBe(
        false
      );
    }
  );

  test.each([
    "/api",
    "/api/docs",
    "/api/docs/oauth2-redirect",
    "/api/chat/mcp/oauth/callback",
    "/api/build/sessions/session-id/webapp/_next/hmr",
  ])("keeps the page proxy on routes outside the API catch-all: %s", (path) => {
    expect(
      unstable_doesMiddlewareMatch({
        config,
        url: origin + path,
      })
    ).toBe(true);
  });
});

describe("API route response policies", () => {
  beforeEach(() => {
    jest.replaceProperty(process, "env", {
      ...process.env,
      OVERRIDE_API_PRODUCTION: "true",
    });
  });
  afterEach(() => jest.restoreAllMocks());

  test("POST streams multipart input and adds CSP to a backend error", async () => {
    const form = new FormData();
    form.set("file", new Blob(["bundle contents"]), "skill.zip");
    const request = new NextRequest(
      origin + "/api/skills/custom?inspect=true",
      {
        method: "POST",
        body: form,
        headers: { [ORIGINAL_PATH_HEADER]: "/spoofed" },
      }
    );
    const backend = new Response("bundle too large", { status: 413 });
    const fetchSpy = jest.spyOn(global, "fetch").mockResolvedValue(backend);
    const response = await POST(request, {
      params: Promise.resolve({ path: ["skills", "custom"] }),
    });
    const page = await proxy(new NextRequest(origin + "/app"));
    expect(fetchSpy).toHaveBeenCalledWith(
      expect.any(URL),
      expect.objectContaining({
        method: "POST",
        body: request.body,
        duplex: "half",
        redirect: "manual",
      })
    );
    const options = fetchSpy.mock.calls[0]?.[1];
    const headers = new Headers(options?.headers);
    expect(headers.get(ORIGINAL_PATH_HEADER)).toBe(
      "/api/skills/custom?inspect=true"
    );
    expect(headers.get("content-type")).toContain(
      "multipart/form-data; boundary="
    );
    expect(request.bodyUsed).toBe(false);
    expect(response.headers.get("Content-Security-Policy")).toBe(
      page.headers.get("Content-Security-Policy")
    );
    expect(response.headers.get("Content-Security-Policy")).toContain(
      "object-src 'none'"
    );
    expect(response.status).toBe(413);
    expect(response.bodyUsed).toBe(false);
    expect(backend.bodyUsed).toBe(false);
    expect(await response.text()).toBe("bundle too large");
    expect(await request.text()).toContain("bundle contents");
  });

  test.each(["text/html", "text/event-stream"])(
    "GET preserves backend sandbox policy for %s",
    async (contentType) => {
      const backend = new Response("safe response", {
        headers: {
          "Content-Security-Policy": "sandbox; default-src 'none'",
          "Content-Type": contentType,
          "X-Content-Type-Options": "nosniff",
          "Set-Cookie": "test=value; HttpOnly",
        },
      });
      jest.spyOn(global, "fetch").mockResolvedValue(backend);
      const response = await GET(
        new NextRequest(origin + "/api/chat/file/test"),
        {
          params: Promise.resolve({ path: ["chat", "file", "test"] }),
        }
      );
      expect(response.headers.get("Content-Security-Policy")).toBe(
        "sandbox; default-src 'none', frame-ancestors 'self' chrome-extension: moz-extension:;"
      );
      expect(response.headers.get("X-Content-Type-Options")).toBe("nosniff");
      expect(response.headers.get("Set-Cookie")).toContain("test=value");
      expect(response.bodyUsed).toBe(false);
      expect(await response.text()).toBe("safe response");
    }
  );

  test.each([
    ["true", "sandbox; frame-ancestors 'none'"],
    ["true", "sandbox; frame-ancestors https://example.com"],
    ["false", "sandbox; default-src 'none'"],
  ])(
    "preserves the backend policy with frame protection %s",
    (enabled, policy) => {
      process.env.WEB_FRAME_PROTECTION_ENABLED = enabled;
      jest.isolateModules(() => {
        const { withSecurityHeaders } =
          jest.requireActual<typeof import("@/securityHeaders")>(
            "@/securityHeaders"
          );
        const response = withSecurityHeaders(
          new NextResponse(null, {
            headers: { "Content-Security-Policy": policy },
          })
        );
        expect(response.headers.get("Content-Security-Policy")).toBe(
          enabled === "true"
            ? `${policy}, frame-ancestors 'self' chrome-extension: moz-extension:;`
            : policy
        );
      });
    }
  );

  test("invalid Sentry configuration warns without its value", () => {
    process.env.NEXT_PUBLIC_SENTRY_DSN = "private-invalid-DSN";
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    jest.isolateModules(() => {
      jest.requireActual<typeof import("@/securityHeaders")>(
        "@/securityHeaders"
      );
    });
    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining("NEXT_PUBLIC_SENTRY_DSN")
    );
    expect(JSON.stringify(warn.mock.calls)).not.toContain(
      "private-invalid-DSN"
    );
  });
});
