import useSWR from "swr";
import {
  useSettings,
  useEnterpriseSettings,
  useCustomAnalyticsScript,
} from "@/hooks/useSettings";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ApplicationStatus, QueryHistoryType } from "@/interfaces/settings";

jest.mock("swr", () => ({
  __esModule: true,
  default: jest.fn(),
}));

jest.mock("@/lib/fetcher", () => ({
  errorHandlingFetcher: jest.fn(),
}));

jest.mock("@/lib/constants", () => ({
  EE_ENABLED: false,
}));

const mockUseSWR = useSWR as jest.MockedFunction<typeof useSWR>;

describe("useSettings", () => {
  beforeEach(() => {
    mockUseSWR.mockReset();
  });

  test("returns DEFAULT_SETTINGS when SWR data is undefined", () => {
    mockUseSWR.mockReturnValue({
      data: undefined,
      error: undefined,
      isLoading: true,
      mutate: jest.fn(),
      isValidating: false,
    } as any);

    const result = useSettings();

    expect(result.settings).toEqual({
      auto_scroll: true,
      application_status: ApplicationStatus.ACTIVE,
      gpu_enabled: false,
      maximum_chat_retention_days: null,
      notifications: [],
      needs_reindexing: false,
      anonymous_user_enabled: false,
      invite_only_enabled: false,
      deep_research_enabled: true,
      multi_model_chat_enabled: true,
      temperature_override_enabled: true,
      query_history_type: QueryHistoryType.NORMAL,
    });
    expect(result.isLoading).toBe(true);
  });

  test("returns fetched settings when SWR has data", () => {
    const mockSettings = {
      auto_scroll: false,
      application_status: ApplicationStatus.ACTIVE,
      gpu_enabled: true,
      maximum_chat_retention_days: 30,
      notifications: [],
      needs_reindexing: false,
      anonymous_user_enabled: false,
      invite_only_enabled: false,
      deep_research_enabled: true,
      multi_model_chat_enabled: true,
      temperature_override_enabled: true,
      query_history_type: QueryHistoryType.NORMAL,
    };

    mockUseSWR.mockReturnValue({
      data: mockSettings,
      error: undefined,
      isLoading: false,
      mutate: jest.fn(),
      isValidating: false,
    } as any);

    const result = useSettings();

    expect(result.settings).toBe(mockSettings);
    expect(result.isLoading).toBe(false);
    expect(result.error).toBeUndefined();
  });

  test("fetches from /api/settings with correct SWR config", () => {
    mockUseSWR.mockReturnValue({
      data: undefined,
      error: undefined,
      isLoading: true,
      mutate: jest.fn(),
      isValidating: false,
    } as any);

    useSettings();

    expect(mockUseSWR).toHaveBeenCalledWith(
      "/api/settings",
      errorHandlingFetcher,
      expect.objectContaining({
        revalidateOnFocus: false,
        revalidateOnReconnect: false,
        dedupingInterval: 30_000,
        errorRetryInterval: 5_000,
      })
    );
  });
});

describe("useEnterpriseSettings", () => {
  beforeEach(() => {
    mockUseSWR.mockReset();
  });

  test("passes null key when EE is disabled at both build and runtime", () => {
    mockUseSWR.mockReturnValue({
      data: undefined,
      error: undefined,
      isLoading: false,
      mutate: jest.fn(),
      isValidating: false,
    } as any);

    const result = useEnterpriseSettings(false);

    expect(mockUseSWR).toHaveBeenCalledWith(
      null,
      errorHandlingFetcher,
      expect.any(Object)
    );
    expect(result.enterpriseSettings).toBeNull();
    expect(result.isLoading).toBe(false);
  });

  test("fetches from /api/enterprise-settings when runtime EE is enabled", () => {
    mockUseSWR.mockReturnValue({
      data: undefined,
      error: undefined,
      isLoading: true,
      mutate: jest.fn(),
      isValidating: false,
    } as any);

    useEnterpriseSettings(true);

    expect(mockUseSWR).toHaveBeenCalledWith(
      "/api/enterprise-settings",
      errorHandlingFetcher,
      expect.any(Object)
    );
  });

  test("uses referential equality for compare to ensure logo cache-busters update", () => {
    mockUseSWR.mockReturnValue({
      data: undefined,
      error: undefined,
      isLoading: true,
      mutate: jest.fn(),
      isValidating: false,
    } as any);

    useEnterpriseSettings(true);

    const swrConfig = mockUseSWR.mock.calls[0]![2] as any;
    expect(swrConfig.compare).toBeDefined();

    // Same reference should be equal
    const obj = { use_custom_logo: true };
    expect(swrConfig.compare(obj, obj)).toBe(true);

    // Different references with same values should NOT be equal
    // (this is the key behavior — SWR's default deep compare would return true)
    const a = { use_custom_logo: true };
    const b = { use_custom_logo: true };
    expect(swrConfig.compare(a, b)).toBe(false);
  });

  test("returns enterprise settings when SWR has data", () => {
    const mockEnterprise = {
      application_name: "Acme Corp",
      use_custom_logo: true,
    };

    mockUseSWR.mockReturnValue({
      data: mockEnterprise,
      error: undefined,
      isLoading: false,
      mutate: jest.fn(),
      isValidating: false,
    } as any);

    const result = useEnterpriseSettings(true);

    expect(result.enterpriseSettings).toBe(mockEnterprise);
    expect(result.isLoading).toBe(false);
  });
});

describe("useCustomAnalyticsScript", () => {
  beforeEach(() => {
    mockUseSWR.mockReset();
  });

  test("returns null when EE is disabled", () => {
    mockUseSWR.mockReturnValue({
      data: undefined,
      error: undefined,
      isLoading: false,
      mutate: jest.fn(),
      isValidating: false,
    } as any);

    const result = useCustomAnalyticsScript(false);

    expect(mockUseSWR).toHaveBeenCalledWith(
      null,
      errorHandlingFetcher,
      expect.any(Object)
    );
    expect(result).toBeNull();
  });

  test("returns script content when available", () => {
    const script = "console.log('analytics');";
    mockUseSWR.mockReturnValue({
      data: script,
      error: undefined,
      isLoading: false,
      mutate: jest.fn(),
      isValidating: false,
    } as any);

    const result = useCustomAnalyticsScript(true);

    expect(result).toBe(script);
  });
});
