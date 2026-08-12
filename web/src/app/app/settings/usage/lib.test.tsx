import { renderHook } from "@testing-library/react";
import useSWR from "swr";
import { useUserUsage } from "@/app/app/settings/usage/lib";

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
});
