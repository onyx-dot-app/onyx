import { renderHook } from "@testing-library/react";
import useSWR from "swr";
import { useUserUsage } from "@/app/app/settings/usage/lib";
import { rangeForInclusiveDays } from "@/refresh-components/DateRangePicker";

jest.mock("swr", () => jest.fn());

const mockUseSWR = useSWR as jest.MockedFunction<typeof useSWR>;

describe("useUserUsage", () => {
  beforeEach(() => {
    mockUseSWR.mockReturnValue({
      data: undefined,
      error: undefined,
      isLoading: false,
    } as ReturnType<typeof useSWR>);
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it("requests inclusive calendar start and end dates", () => {
    renderHook(() =>
      useUserUsage({
        from: new Date(2026, 6, 6),
        to: new Date(2026, 7, 4, 23, 59, 59, 999),
      })
    );

    expect(mockUseSWR).toHaveBeenCalledWith(
      "/api/user/usage?start=2026-07-06&end=2026-08-04",
      expect.any(Function),
      expect.objectContaining({ revalidateOnFocus: false })
    );
  });

  it("anchors preset ranges to the current UTC usage day", () => {
    const nowBeforeUtcDayRollover = new Date("2026-08-13T05:00:00+10:00");

    renderHook(() =>
      useUserUsage(rangeForInclusiveDays(1, nowBeforeUtcDayRollover))
    );

    expect(mockUseSWR).toHaveBeenCalledWith(
      "/api/user/usage?start=2026-08-12&end=2026-08-12",
      expect.any(Function),
      expect.objectContaining({ revalidateOnFocus: false })
    );
  });
});
