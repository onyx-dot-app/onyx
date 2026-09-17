import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  jest,
} from "@jest/globals";
import { act, renderHook } from "@testing-library/react-native";
import type { Mock } from "jest-mock";
import { AppState, type AppStateStatus } from "react-native";

import { refreshToken } from "@/api/auth/sessionManager";
import { useTokenRefresh } from "@/hooks/useTokenRefresh";

// Factory mock, not automock: evaluating the real module pulls in MMKV-backed session storage.
jest.mock("@/api/auth/sessionManager", () => ({
  refreshToken: jest.fn(),
}));

const mockRefreshToken = refreshToken as unknown as Mock<
  () => Promise<string | null>
>;

const REFRESH_INTERVAL_MS = 600_000;

// `AppState.currentState` is a plain data property on the RN module, so it's assigned, not spied.
let emitAppState: (status: AppStateStatus) => void;

beforeEach(() => {
  jest.useFakeTimers();
  jest.clearAllMocks();
  mockRefreshToken.mockResolvedValue("tok");

  AppState.currentState = "active";
  emitAppState = () => {};
  jest
    .spyOn(AppState, "addEventListener")
    .mockImplementation((_type, listener) => {
      emitAppState = (status) => {
        AppState.currentState = status;
        (listener as (status: AppStateStatus) => void)(status);
      };
      return { remove: jest.fn() } as unknown as ReturnType<
        typeof AppState.addEventListener
      >;
    });
});

afterEach(() => {
  jest.useRealTimers();
  jest.restoreAllMocks();
});

describe("useTokenRefresh", () => {
  it("refreshes once as soon as identity is confirmed", () => {
    renderHook(() => useTokenRefresh(true));

    expect(mockRefreshToken).toHaveBeenCalledTimes(1);
  });

  it("stays idle until identity is confirmed", () => {
    const { rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) => useTokenRefresh(enabled),
      { initialProps: { enabled: false } },
    );
    expect(mockRefreshToken).not.toHaveBeenCalled();

    rerender({ enabled: true });
    expect(mockRefreshToken).toHaveBeenCalledTimes(1);
  });

  it("refreshes on each interval tick while the app is foregrounded", () => {
    renderHook(() => useTokenRefresh(true));
    mockRefreshToken.mockClear();

    act(() => {
      jest.advanceTimersByTime(REFRESH_INTERVAL_MS);
    });
    expect(mockRefreshToken).toHaveBeenCalledTimes(1);

    act(() => {
      jest.advanceTimersByTime(REFRESH_INTERVAL_MS);
    });
    expect(mockRefreshToken).toHaveBeenCalledTimes(2);
  });

  it("skips interval ticks that fire while backgrounded", () => {
    renderHook(() => useTokenRefresh(true));
    mockRefreshToken.mockClear();

    act(() => {
      emitAppState("background");
      jest.advanceTimersByTime(REFRESH_INTERVAL_MS * 3);
    });

    expect(mockRefreshToken).not.toHaveBeenCalled();
  });

  it("refreshes on returning to the foreground — the only trigger that survives a suspend", () => {
    renderHook(() => useTokenRefresh(true));
    mockRefreshToken.mockClear();

    act(() => {
      emitAppState("background");
      // iOS suspends JS timers here, so no interval tick lands during the gap.
      jest.setSystemTime(Date.now() + 60 * 60 * 1000);
      emitAppState("active");
    });

    expect(mockRefreshToken).toHaveBeenCalledTimes(1);
  });

  it("ignores a foreground bounce within the minimum gap", () => {
    renderHook(() => useTokenRefresh(true)); // mount attempt consumes the gap
    mockRefreshToken.mockClear();

    act(() => {
      emitAppState("background");
      emitAppState("active");
    });

    expect(mockRefreshToken).not.toHaveBeenCalled();
  });

  it("swallows a failed refresh rather than rejecting unhandled", async () => {
    mockRefreshToken.mockRejectedValue(new Error("offline"));

    renderHook(() => useTokenRefresh(true));
    await act(async () => {});

    expect(mockRefreshToken).toHaveBeenCalledTimes(1);
  });

  it("stops refreshing once unmounted", () => {
    const { unmount } = renderHook(() => useTokenRefresh(true));
    mockRefreshToken.mockClear();

    unmount();
    act(() => {
      jest.advanceTimersByTime(REFRESH_INTERVAL_MS * 2);
    });

    expect(mockRefreshToken).not.toHaveBeenCalled();
  });
});
