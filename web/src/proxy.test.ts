import { NextRequest } from "next/server";
import { proxy } from "./proxy";

// Mock the constants module
jest.mock("./lib/constants", () => ({
  SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED: false,
  SERVER_SIDE_ONLY__AUTH_TYPE: "basic",
}));

// Mock the getDomain function
jest.mock("./lib/redirectSS", () => ({
  getDomain: jest.fn((request: NextRequest) => {
    // Check for WEB_DOMAIN env var
    if (process.env.WEB_DOMAIN) {
      return process.env.WEB_DOMAIN;
    }

    // Check for X-Forwarded headers
    const requestedHost = request.headers.get("X-Forwarded-Host");
    const requestedProto = request.headers.get("X-Forwarded-Proto");
    if (requestedHost) {
      const protocol = requestedProto || "http";
      return `${protocol}://${requestedHost}`;
    }

    // Fall back to request URL origin
    return request.nextUrl.origin;
  }),
}));

describe("proxy middleware", () => {
  const originalEnv = process.env;

  beforeEach(() => {
    jest.clearAllMocks();
    // Reset environment
    process.env = { ...originalEnv };
    delete process.env.WEB_DOMAIN;
  });

  afterAll(() => {
    process.env = originalEnv;
  });

  describe("authentication redirect with reverse proxy headers", () => {
    it("should create absolute HTTPS redirect when X-Forwarded-Proto is https", async () => {
      // Simulate a request from a reverse proxy that has terminated TLS
      const headers = new Headers({
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": "onyx.example.com",
      });

      const request = new NextRequest(
        new Request("http://localhost:3000/chat", {
          headers,
        })
      );

      const response = await proxy(request);

      expect(response).toBeDefined();
      expect(response?.status).toBe(307);

      const location = response?.headers.get("location");
      expect(location).toBeTruthy();
      expect(location).toMatch(/^https:\/\/onyx\.example\.com\/auth\/login/);
      expect(location).toContain("next=%2Fchat");
    });

    it("should use WEB_DOMAIN env var when set", async () => {
      process.env.WEB_DOMAIN = "https://onyx.corporate.com";

      const headers = new Headers({
        "X-Forwarded-Proto": "http", // Even with http header
        "X-Forwarded-Host": "wrong.example.com",
      });

      const request = new NextRequest(
        new Request("http://localhost:3000/chat", {
          headers,
        })
      );

      const response = await proxy(request);

      expect(response).toBeDefined();
      expect(response?.status).toBe(307);

      const location = response?.headers.get("location");
      expect(location).toBeTruthy();
      // Should use WEB_DOMAIN, ignoring X-Forwarded headers
      expect(location).toMatch(/^https:\/\/onyx\.corporate\.com\/auth\/login/);
    });

    it("should preserve query params and hash in redirect", async () => {
      const headers = new Headers({
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": "onyx.example.com",
      });

      const request = new NextRequest(
        new Request("http://localhost:3000/chat?foo=bar#section", {
          headers,
        })
      );

      const response = await proxy(request);

      expect(response).toBeDefined();
      const location = response?.headers.get("location");
      expect(location).toBeTruthy();
      expect(location).toContain("next=%2Fchat%3Ffoo%3Dbar%23section");
    });

    it("should handle requests without X-Forwarded headers", async () => {
      // Direct request without reverse proxy
      const request = new NextRequest(
        new Request("http://localhost:3000/chat")
      );

      const response = await proxy(request);

      expect(response).toBeDefined();
      expect(response?.status).toBe(307);

      const location = response?.headers.get("location");
      expect(location).toBeTruthy();
      // Should use the request URL's origin
      expect(location).toMatch(/^http:\/\/localhost:3000\/auth\/login/);
    });
  });

  describe("authentication bypass", () => {
    it("should allow access to public routes without auth", async () => {
      const request = new NextRequest(
        new Request("http://localhost:3000/auth/login")
      );

      const response = await proxy(request);

      // Should pass through (NextResponse.next())
      expect(response?.status).not.toBe(307);
    });

    it("should allow access with valid auth cookie", async () => {
      const headers = new Headers({
        Cookie: "fastapiusersauth=valid-token",
      });

      const request = new NextRequest(
        new Request("http://localhost:3000/chat", {
          headers,
        })
      );

      const response = await proxy(request);

      // Should pass through (NextResponse.next())
      expect(response?.status).not.toBe(307);
    });
  });

  describe("protected routes", () => {
    const protectedRoutes = ["/chat", "/admin", "/assistants", "/connector"];

    protectedRoutes.forEach((route) => {
      it(`should redirect ${route} when not authenticated`, async () => {
        const headers = new Headers({
          "X-Forwarded-Proto": "https",
          "X-Forwarded-Host": "onyx.example.com",
        });

        const request = new NextRequest(
          new Request(`http://localhost:3000${route}`, {
            headers,
          })
        );

        const response = await proxy(request);

        expect(response).toBeDefined();
        expect(response?.status).toBe(307);

        const location = response?.headers.get("location");
        expect(location).toBeTruthy();
        expect(location).toMatch(/^https:\/\/onyx\.example\.com\/auth\/login/);
      });
    });
  });
});
