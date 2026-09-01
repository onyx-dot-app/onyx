/**
 * @jest-environment jsdom
 */
import { renderHook } from "@testing-library/react";
import useSWR from "swr";
import { usePathname } from "next/navigation";
import { FetchError } from "@/lib/fetcher";
import { useSettings } from "@/lib/settings/hooks";
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

function swrResult(overrides: { error?: Error } = {}) {
  return {
    data: undefined,
    error: undefined,
    mutate: jest.fn(),
    isValidating: false,
    isLoading: false,
    ...overrides,
  } as unknown as ReturnType<typeof useSWR>;
}

function stubEnterpriseFetchError(error: Error) {
  mockUseSWR.mockImplementation((key) =>
    key === SWR_KEYS.enterpriseSettings ? swrResult({ error }) : swrResult()
  );
}

function enterpriseRetryPolicy(): (err: Error) => boolean {
  const call = mockUseSWR.mock.calls.find(
    ([key]) => key === SWR_KEYS.enterpriseSettings
  );
  expect(call).toBeDefined();
  const config = call?.[2] as { shouldRetryOnError: (err: Error) => boolean };
  return config.shouldRetryOnError;
}

// A CE backend has no enterprise-settings route. The login page probes it
// anyway, so the 404 must degrade to default branding, not a fatal error.
describe("useSettings enterprise-settings 404 handling", () => {
  beforeEach(() => {
    mockUseSWR.mockReset();
    mockUsePathname.mockReset();
    mockUsePathname.mockReturnValue("/auth/login");
  });

  test("a 404 yields default branding with no error and no retry", () => {
    const missing = new FetchError("Not Found", 404, {});
    stubEnterpriseFetchError(missing);
    const { result } = renderHook(() => useSettings());
    expect(result.current.error).toBeUndefined();
    expect(result.current.enterprise).toBeNull();
    expect(result.current.appName).toBe("Onyx");
    expect(result.current.logoUrl).toBeNull();
    expect(enterpriseRetryPolicy()(missing)).toBe(false);
  });

  test("a 404 off the auth path is not surfaced either", () => {
    mockUsePathname.mockReturnValue("/app");
    stubEnterpriseFetchError(new FetchError("Not Found", 404, {}));
    const { result } = renderHook(() => useSettings());
    expect(result.current.error).toBeUndefined();
    expect(result.current.enterprise).toBeNull();
  });

  test("other enterprise-settings failures still surface and retry", () => {
    const outage = new FetchError("Internal Server Error", 500, {});
    stubEnterpriseFetchError(outage);
    const { result } = renderHook(() => useSettings());
    expect(result.current.error).toBe(outage);
    expect(enterpriseRetryPolicy()(outage)).toBe(true);
  });
});
