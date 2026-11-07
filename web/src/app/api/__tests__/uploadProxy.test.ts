import { unstable_doesMiddlewareMatch } from "next/experimental/testing/server";
import { NextRequest, NextResponse } from "next/server";
import { config, proxy } from "@/proxy";
import { withSecurityHeaders } from "@/securityHeaders";

const origin = "http://localhost:3000";

// Exercise Next's matcher rather than calling proxy() on excluded requests.
describe("multipart upload routing", () => {
  test.each([
    "/api/skills/custom",
    "/api/user/projects/file/upload",
    "/api/manage/admin/connector/file",
    "/api/build/user-library/files",
  ])("streams %s without cloning the body", (path) => {
    expect(
      unstable_doesMiddlewareMatch({
        config,
        url: origin + path,
        headers: { "content-type": "multipart/form-data; boundary=test" },
      })
    ).toBe(false);
  });

  test.each(["multipart/form-data", "Multipart/Form-Data; boundary=test"])(
    "recognizes %s",
    (contentType) => {
      expect(
        unstable_doesMiddlewareMatch({
          config,
          url: origin + "/api/skills/custom",
          headers: { "content-type": contentType },
        })
      ).toBe(false);
    }
  );

  test.each(["/admin/users", "/agents", "/connector", "/app", "/apiary"])(
    "keeps the page proxy for multipart requests to %s",
    (path) => {
      expect(
        unstable_doesMiddlewareMatch({
          config,
          url: origin + path,
          headers: { "content-type": "multipart/form-data; boundary=test" },
        })
      ).toBe(true);
    }
  );

  test.each(["/api/auth/login", "/api/docs", "/api/chat/mcp/oauth/callback"])(
    "keeps the proxy for non-upload requests to %s",
    (path) => {
      expect(unstable_doesMiddlewareMatch({ config, url: origin + path })).toBe(
        true
      );
    }
  );

  test.each([
    "/api/docs",
    "/api/docs/oauth2-redirect",
    "/api/chat/mcp/oauth/callback",
    "/api/build/sessions/session-id/webapp/_next/hmr",
  ])(
    "keeps security headers on routes outside the API catch-all: %s",
    (path) => {
      expect(
        unstable_doesMiddlewareMatch({
          config,
          url: origin + path,
          headers: { "content-type": "multipart/form-data; boundary=test" },
        })
      ).toBe(true);
    }
  );

  test("uses the page CSP on streamed API responses without reading the body", async () => {
    const body = new ReadableStream<Uint8Array>();
    const response = withSecurityHeaders(
      new NextResponse(body, { status: 413 })
    );
    const page = await proxy(new NextRequest(origin + "/app"));
    expect(response.headers.get("Content-Security-Policy")).toBe(
      page.headers.get("Content-Security-Policy")
    );
    expect(response.headers.get("Content-Security-Policy")).toContain(
      "object-src 'none'"
    );
    expect(response.bodyUsed).toBe(false);
    expect(response.status).toBe(413);
    await response.body?.cancel();
  });
});
