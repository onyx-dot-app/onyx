import { headers } from "next/headers";
import { requireAuth } from "./requireAuth";
import { getAuthTypeMetadataSS, getCurrentUserSS } from "@/lib/userSS";
import { User } from "@/lib/types";

jest.mock("next/headers", () => ({
  headers: jest.fn(),
}));

jest.mock("@/lib/userSS", () => ({
  getAuthTypeMetadataSS: jest.fn(),
  getCurrentUserSS: jest.fn(),
}));

const mockHeaders = headers as jest.MockedFunction<typeof headers>;
const mockGetAuthTypeMetadataSS = getAuthTypeMetadataSS as jest.MockedFunction<
  typeof getAuthTypeMetadataSS
>;
const mockGetCurrentUserSS = getCurrentUserSS as jest.MockedFunction<
  typeof getCurrentUserSS
>;

function mockHeaderValue(value: string | null): void {
  mockHeaders.mockResolvedValue({
    get: (key: string) => (key === "x-pathname" ? value : null),
  } as unknown as ReturnType<typeof headers>);
}

function mockUnauthenticated(): void {
  mockGetAuthTypeMetadataSS.mockResolvedValue({
    authType: "basic",
    autoRedirect: false,
    hasUsers: true,
    requiresVerification: false,
    anonymousUserEnabled: false,
  } as never);
  mockGetCurrentUserSS.mockResolvedValue(null);
}

describe("requireAuth login redirect", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("redirects to login with next param for a shared-chat URL", async () => {
    mockHeaderValue("/app/shared/abc123");
    mockUnauthenticated();

    const result = await requireAuth();

    expect(result.redirect).toBe("/auth/login?next=%2Fapp%2Fshared%2Fabc123");
  });

  it("preserves query strings in the next param", async () => {
    mockHeaderValue("/app/shared/abc123?message=m42");
    mockUnauthenticated();

    const result = await requireAuth();

    expect(result.redirect).toBe(
      "/auth/login?next=%2Fapp%2Fshared%2Fabc123%3Fmessage%3Dm42"
    );
  });

  it("falls back to bare /auth/login for a protocol-relative URL", async () => {
    mockHeaderValue("//evil.com/phish");
    mockUnauthenticated();

    const result = await requireAuth();

    expect(result.redirect).toBe("/auth/login");
  });

  it("falls back to bare /auth/login for a javascript: path", async () => {
    mockHeaderValue("/javascript:alert(1)");
    mockUnauthenticated();

    const result = await requireAuth();

    expect(result.redirect).toBe("/auth/login");
  });

  it("omits next when the pathname is already /auth/login", async () => {
    mockHeaderValue("/auth/login");
    mockUnauthenticated();

    const result = await requireAuth();

    expect(result.redirect).toBe("/auth/login");
  });

  it("falls back gracefully when the x-pathname header is missing", async () => {
    mockHeaderValue(null);
    mockUnauthenticated();

    const result = await requireAuth();

    expect(result.redirect).toBe("/auth/login");
  });

  it("does not redirect an authenticated, verified user", async () => {
    mockHeaderValue("/app/shared/abc123");
    mockGetAuthTypeMetadataSS.mockResolvedValue({
      authType: "basic",
      autoRedirect: false,
      hasUsers: true,
      requiresVerification: false,
      anonymousUserEnabled: false,
    } as never);
    mockGetCurrentUserSS.mockResolvedValue({
      id: "u1",
      is_verified: true,
    } as User);

    const result = await requireAuth();

    expect(result.redirect).toBeUndefined();
    expect(result.user).toBeTruthy();
  });
});
