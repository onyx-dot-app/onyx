import { NextRequest } from "next/server";
import { getDomain, getForwardedHostHeaders } from "@/lib/redirectSS";

const WEB_DOMAIN = "https://cloud.example.com";
const ALTERNATE = "https://agent.customer.example";

function requestWithHeaders(headers: Record<string, string>): NextRequest {
  return new NextRequest("http://web-server:3000/auth/oauth/callback", {
    headers,
  });
}

const originalEnv = process.env;

beforeEach(() => {
  process.env = {
    ...originalEnv,
    WEB_DOMAIN,
    ALTERNATE_WEB_DOMAINS: `${ALTERNATE}/, http://127.0.0.1:3000`,
  };
});

afterEach(() => {
  process.env = originalEnv;
});

describe("getDomain", () => {
  it.each([
    [{ host: "agent.customer.example" }, ALTERNATE],
    [{ "x-forwarded-host": "agent.customer.example" }, ALTERNATE],
    [{ host: "127.0.0.1:3000" }, "http://127.0.0.1:3000"],
    [{ host: "cloud.example.com" }, WEB_DOMAIN],
    [{ host: "evil.example" }, WEB_DOMAIN],
    [{ "x-forwarded-host": "evil.example" }, WEB_DOMAIN],
  ])("maps %j to %s", (headers, expected) => {
    expect(getDomain(requestWithHeaders(headers))).toBe(expected);
  });

  it("ignores the host when no alternate web domains are set", () => {
    process.env.ALTERNATE_WEB_DOMAINS = "";
    expect(
      getDomain(requestWithHeaders({ host: "agent.customer.example" }))
    ).toBe(WEB_DOMAIN);
  });
});

describe("getForwardedHostHeaders", () => {
  it("forwards the selected web domain's host", () => {
    expect(
      getForwardedHostHeaders(
        requestWithHeaders({ host: "agent.customer.example" })
      )
    ).toEqual({ "x-forwarded-host": "agent.customer.example" });
  });
});
