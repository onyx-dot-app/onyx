/**
 * @jest-environment jsdom
 */
import { renderHook } from "@testing-library/react";
import useSWR from "swr";
import { usePathname } from "next/navigation";
import { isAuthPath, loginPath } from "@/lib/auth/paths";
import { useSettings } from "@/lib/settings/hooks";
import { useLLMProviders } from "@/lib/languageModels/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";

jest.mock("swr", () => ({
  __esModule: true,
  default: jest.fn(),
}));

jest.mock("next/navigation", () => ({
  ...jest.requireActual("next/navigation"),
  usePathname: jest.fn(),
}));

const mockUseSWR = useSWR as jest.MockedFunction<typeof useSWR>;
const mockUsePathname = usePathname as jest.MockedFunction<typeof usePathname>;

function swrStub() {
  return {
    data: undefined,
    error: undefined,
    mutate: jest.fn(),
    isValidating: false,
    isLoading: false,
  } as unknown as ReturnType<typeof useSWR>;
}

describe("isAuthPath", () => {
  test.each([
    ["/auth/login", true],
    ["/auth", true],
    // Segment match, not a bare prefix: a route that merely starts with "auth"
    // is not an auth page.
    ["/authoring", false],
    ["/chat", false],
    [null, false],
  ])("isAuthPath(%s) === %s", (path, expected) => {
    expect(isAuthPath(path as string | null | undefined)).toBe(expected);
  });
});

describe("loginPath", () => {
  test("is the bare login page with nothing to carry", () => {
    expect(loginPath()).toBe("/auth/login");
    expect(loginPath({ next: null })).toBe("/auth/login");
  });

  test("keeps the query of the page the user arrived on", () => {
    expect(loginPath({ next: "/app?user-prompt=hello%20world" })).toBe(
      "/auth/login?next=%2Fapp%3Fuser-prompt%3Dhello%2520world"
    );
  });

  test("drops a next that would leave the site", () => {
    expect(loginPath({ next: "https://evil.example.com/app" })).toBe(
      "/auth/login"
    );
    expect(loginPath({ next: "//evil.example.com" })).toBe("/auth/login");
  });

  test("adds the SSO escape hatch only when asked to hold", () => {
    expect(loginPath({ next: "/app", autoRedirectToSso: false })).toBe(
      "/auth/login?next=%2Fapp&autoRedirectToSso=false"
    );
    expect(loginPath({ autoRedirectToSso: true })).toBe("/auth/login");
  });
});

describe("app-shell fetches are gated on /auth/* routes", () => {
  beforeEach(() => {
    mockUseSWR.mockReset();
    mockUseSWR.mockReturnValue(swrStub());
    mockUsePathname.mockReset();
  });

  // The core settings request is the first useSWR call in useSettings; the
  // second is enterprise settings, which stays enabled so login branding works.
  test("useSettings skips the core settings fetch on /auth/*", () => {
    mockUsePathname.mockReturnValue("/auth/login");
    renderHook(() => useSettings());
    expect(mockUseSWR.mock.calls[0]?.[0]).toBeNull();
  });

  test("useSettings fetches core settings off /auth/*", () => {
    mockUsePathname.mockReturnValue("/chat");
    renderHook(() => useSettings());
    expect(mockUseSWR.mock.calls[0]?.[0]).toBe(SWR_KEYS.settings);
  });

  test("useLLMProviders skips the providers fetch on /auth/*", () => {
    mockUsePathname.mockReturnValue("/auth/login");
    renderHook(() => useLLMProviders());
    expect(mockUseSWR.mock.calls[0]?.[0]).toBeNull();
  });

  test("useLLMProviders fetches providers off /auth/*", () => {
    mockUsePathname.mockReturnValue("/chat");
    renderHook(() => useLLMProviders());
    expect(mockUseSWR.mock.calls[0]?.[0]).toBe(SWR_KEYS.llmProviders);
  });
});
